"""Load balancing module"""
import random
import asyncio
from typing import Optional
from collections import defaultdict
from ..core.models import Token
from ..core.config import config
from .token_manager import TokenManager
from .token_lock import TokenLock
from .concurrency_manager import ConcurrencyManager
from ..core.logger import debug_logger

class LoadBalancer:
    """Token load balancer with random selection and round-robin polling"""

    def __init__(self, token_manager: TokenManager, concurrency_manager: Optional[ConcurrencyManager] = None):
        self.token_manager = token_manager
        self.concurrency_manager = concurrency_manager
        # Use image timeout from config as lock timeout
        self.token_lock = TokenLock(lock_timeout=config.image_timeout)
        # Round-robin state: stores last used token_id for each scenario (image/video/default)
        # Resets to None on restart
        self._round_robin_state = {"image": None, "video": None, "default": None}
        self._rr_lock = asyncio.Lock()

    async def _select_round_robin(self, tokens: list[Token], scenario: str) -> Optional[Token]:
        """Select tokens in round-robin order for the given scenario"""
        if not tokens:
            return None
        tokens_sorted = sorted(tokens, key=lambda t: t.id)

        async with self._rr_lock:
            last_id = self._round_robin_state.get(scenario)
            start_idx = 0
            if last_id is not None:
                # Find the position of last used token and move to next
                for idx, token in enumerate(tokens_sorted):
                    if token.id == last_id:
                        start_idx = (idx + 1) % len(tokens_sorted)
                        break
            selected = tokens_sorted[start_idx]
            # Update state for next selection
            self._round_robin_state[scenario] = selected.id

        return selected

    async def select_token(self, for_image_generation: bool = False, for_video_generation: bool = False, require_pro: bool = False) -> Optional[Token]:
        """
        Select a token using random load balancing

        Args:
            for_image_generation: If True, only select tokens that are not locked for image generation and have image_enabled=True
            for_video_generation: If True, filter out tokens with Sora2 quota exhausted (sora2_cooldown_until not expired), tokens that don't support Sora2, and tokens with video_enabled=False
            require_pro: If True, only select tokens with ChatGPT Pro subscription (plan_type="chatgpt_pro")

        Returns:
            Selected token or None if no available tokens
        """
        active_tokens = await self.token_manager.get_active_tokens()

        if not active_tokens:
            return None

        # Filter for Pro tokens if required
        if require_pro:
            pro_tokens = [token for token in active_tokens if token.plan_type == "chatgpt_pro"]
            if not pro_tokens:
                return None
            active_tokens = pro_tokens

        # If for video generation, filter out tokens with Sora2 quota exhausted and tokens without Sora2 support
        if for_video_generation:
            from datetime import datetime

            available_tokens = []

            debug_logger.log_info(f"[VIDEO SELECT] active_tokens count before video filters: {len(active_tokens)}")

            for token in active_tokens:
                remaining = None
                if self.concurrency_manager:
                    remaining = await self.concurrency_manager.get_video_remaining(token.id)

                debug_logger.log_info(
                    f"[VIDEO SELECT] token_id={token.id} "
                    f"email={getattr(token, 'email', None)} "
                    f"is_active={token.is_active} "
                    f"expiry_time={token.expiry_time} "
                    f"video_enabled={token.video_enabled} "
                    f"sora2_supported={token.sora2_supported} "
                    f"sora2_cooldown_until={token.sora2_cooldown_until} "
                    f"video_concurrency_remaining={remaining}"
                )

                if not token.video_enabled:
                    debug_logger.log_info(f"[VIDEO SELECT][SKIP] token {token.id}: video_enabled=False")
                    continue

                if not token.sora2_supported:
                    debug_logger.log_info(f"[VIDEO SELECT][SKIP] token {token.id}: sora2_supported=False/None")
                    continue

                if token.sora2_cooldown_until and token.sora2_cooldown_until <= datetime.now():
                    debug_logger.log_info(f"[VIDEO SELECT] token {token.id}: cooldown expired, refreshing remaining count")
                    await self.token_manager.refresh_sora2_remaining_if_cooldown_expired(token.id)
                    token = await self.token_manager.db.get_token(token.id)

                    remaining = None
                    if self.concurrency_manager:
                        remaining = await self.concurrency_manager.get_video_remaining(token.id)

                    debug_logger.log_info(
                        f"[VIDEO SELECT] token {token.id} after refresh: "
                        f"sora2_supported={token.sora2_supported} "
                        f"sora2_cooldown_until={token.sora2_cooldown_until} "
                        f"video_concurrency_remaining={remaining}"
                    )

                if token and token.sora2_cooldown_until and token.sora2_cooldown_until > datetime.now():
                    debug_logger.log_info(
                        f"[VIDEO SELECT][SKIP] token {token.id}: cooldown active until {token.sora2_cooldown_until}"
                    )
                    continue

                if self.concurrency_manager and not await self.concurrency_manager.can_use_video(token.id):
                    remaining = await self.concurrency_manager.get_video_remaining(token.id)
                    debug_logger.log_info(
                        f"[VIDEO SELECT][SKIP] token {token.id}: video concurrency exhausted, remaining={remaining}"
                    )
                    continue

                debug_logger.log_info(f"[VIDEO SELECT][PASS] token {token.id} accepted for video generation")
                available_tokens.append(token)

            debug_logger.log_info(f"[VIDEO SELECT] available_tokens after filters: {len(available_tokens)}")

            if not available_tokens:
                return None

            active_tokens = available_tokens

        # If for image generation, filter out locked tokens and tokens without image enabled
        if for_image_generation:
            available_tokens = []
            for token in active_tokens:
                # Skip tokens that don't have image enabled
                if not token.image_enabled:
                    continue

                if not await self.token_lock.is_locked(token.id):
                    # Check concurrency limit if concurrency manager is available
                    if self.concurrency_manager and not await self.concurrency_manager.can_use_image(token.id):
                        continue
                    available_tokens.append(token)

            if not available_tokens:
                return None

            # Check if polling mode is enabled
            if config.call_logic_mode == "polling":
                scenario = "image"
                return await self._select_round_robin(available_tokens, scenario)

            # Random selection from available tokens
            return random.choice(available_tokens)
        else:
            # Check if polling mode is enabled
            if config.call_logic_mode == "polling":
                scenario = "video" if for_video_generation else "default"
                return await self._select_round_robin(active_tokens, scenario)

            return random.choice(active_tokens)

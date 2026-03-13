"""Concurrency manager for token-based rate limiting"""
import asyncio
import time
from typing import Dict, Optional
from ..core.logger import debug_logger


class ConcurrencyManager:
    """Manages concurrent request limits for each token"""

    def __init__(self):
        """Initialize concurrency manager"""
        self._image_concurrency: Dict[int, int] = {}  # token_id -> remaining image concurrency
        self._video_concurrency: Dict[int, int] = {}  # token_id -> remaining video concurrency
        self._image_max: Dict[int, int] = {}  # token_id -> configured image concurrency max
        self._video_max: Dict[int, int] = {}  # token_id -> configured video concurrency max
        # TTL tracking: maps token_id to a list of acquisition timestamps (one per held slot)
        # Each entry is a float (time.time() value). When a slot is acquired, a timestamp is
        # appended. When released, the oldest timestamp is popped. Preserving acquisition order keeps age-to-slot mapping stable for TTL expiry.
        # slots have been held longer than SLOT_TTL and force-release them.
        self._image_acquired_at: Dict[int, list] = {}  # token_id -> [timestamp, ...]
        self._video_acquired_at: Dict[int, list] = {}  # token_id -> [timestamp, ...]
        # Tracks count of stale slots already force-released by TTL expiry. A later normal
        # release for the same leaked request should consume this debt instead of changing
        # counters/timestamps for currently active work.
        self._image_stale_release_debt: Dict[int, int] = {}  # token_id -> stale releases to ignore
        self._video_stale_release_debt: Dict[int, int] = {}  # token_id -> stale releases to ignore
        # Maximum time a single slot may be held before it is force-released (seconds).
        # 3600 = 1 hour. In normal operation jobs complete in under 10 min, so this only
        # fires on pathological leaks.
        self.SLOT_TTL: int = 3600
        self._lock = asyncio.Lock()  # Protect concurrent access

    async def initialize(self, tokens: list):
        """
        Initialize concurrency counters from token list
        
        Args:
            tokens: List of Token objects with image_concurrency and video_concurrency fields
        """
        async with self._lock:
            for token in tokens:
                if token.image_concurrency and token.image_concurrency > 0:
                    self._image_concurrency[token.id] = token.image_concurrency
                    self._image_max[token.id] = token.image_concurrency
                if token.video_concurrency and token.video_concurrency > 0:
                    self._video_concurrency[token.id] = token.video_concurrency
                    self._video_max[token.id] = token.video_concurrency
            
            debug_logger.log_info(f"Concurrency manager initialized with {len(tokens)} tokens")

    def _expire_stale_slots(self, token_id: int) -> None:
        """Force-release slots that have been held longer than SLOT_TTL.

        IMPORTANT: This method must only be called while self._lock is already held.
        It modifies _image_concurrency, _video_concurrency, _image_acquired_at, and
        _video_acquired_at in-place.

        Args:
            token_id: The token ID to check and expire stale slots for.
        """
        now = time.time()

        # Expire stale image slots
        if token_id in self._image_acquired_at:
            timestamps = self._image_acquired_at[token_id]
            stale = [ts for ts in timestamps if now - ts > self.SLOT_TTL]
            if stale:
                debug_logger.log_info(
                    f"Token {token_id}: force-releasing {len(stale)} stale image slot(s) "
                    f"held for >{self.SLOT_TTL}s (TTL expiry)"
                )
                for ts in stale:
                    timestamps.remove(ts)
                    if token_id in self._image_concurrency:
                        max_val = self._image_max.get(token_id)
                        if max_val is not None:
                            self._image_concurrency[token_id] = min(
                                self._image_concurrency[token_id] + 1, max_val
                            )
                        else:
                            self._image_concurrency[token_id] += 1
                self._image_stale_release_debt[token_id] = self._image_stale_release_debt.get(token_id, 0) + len(stale)

        # Expire stale video slots
        if token_id in self._video_acquired_at:
            timestamps = self._video_acquired_at[token_id]
            stale = [ts for ts in timestamps if now - ts > self.SLOT_TTL]
            if stale:
                debug_logger.log_info(
                    f"Token {token_id}: force-releasing {len(stale)} stale video slot(s) "
                    f"held for >{self.SLOT_TTL}s (TTL expiry)"
                )
                for ts in stale:
                    timestamps.remove(ts)
                    if token_id in self._video_concurrency:
                        max_val = self._video_max.get(token_id)
                        if max_val is not None:
                            self._video_concurrency[token_id] = min(
                                self._video_concurrency[token_id] + 1, max_val
                            )
                        else:
                            self._video_concurrency[token_id] += 1
                self._video_stale_release_debt[token_id] = self._video_stale_release_debt.get(token_id, 0) + len(stale)

    async def can_use_image(self, token_id: int) -> bool:
        """
        Check if token can be used for image generation
        
        Args:
            token_id: Token ID
            
        Returns:
            True if token has available image concurrency, False if concurrency is 0
        """
        async with self._lock:
            # Expire any stale slots before checking availability
            self._expire_stale_slots(token_id)

            # If not in dict, it means no limit (-1)
            if token_id not in self._image_concurrency:
                return True
            
            remaining = self._image_concurrency[token_id]
            if remaining <= 0:
                debug_logger.log_info(f"Token {token_id} image concurrency exhausted (remaining: {remaining})")
                return False
            
            return True

    async def can_use_video(self, token_id: int) -> bool:
        """
        Check if token can be used for video generation
        
        Args:
            token_id: Token ID
            
        Returns:
            True if token has available video concurrency, False if concurrency is 0
        """
        async with self._lock:
            # Expire any stale slots before checking availability
            self._expire_stale_slots(token_id)

            # If not in dict, it means no limit (-1)
            if token_id not in self._video_concurrency:
                return True
            
            remaining = self._video_concurrency[token_id]
            if remaining <= 0:
                debug_logger.log_info(f"Token {token_id} video concurrency exhausted (remaining: {remaining})")
                return False
            
            return True

    async def acquire_image(self, token_id: int) -> bool:
        """
        Acquire image concurrency slot
        
        Args:
            token_id: Token ID
            
        Returns:
            True if acquired, False if not available
        """
        async with self._lock:
            # Expire stale slots before attempting to acquire
            self._expire_stale_slots(token_id)

            if token_id not in self._image_concurrency:
                # No limit — record timestamp anyway so TTL tracking is consistent
                if token_id not in self._image_acquired_at:
                    self._image_acquired_at[token_id] = []
                self._image_acquired_at[token_id].append(time.time())
                return True
            
            if self._image_concurrency[token_id] <= 0:
                return False

            self._image_concurrency[token_id] -= 1
            if token_id not in self._image_acquired_at:
                self._image_acquired_at[token_id] = []
            self._image_acquired_at[token_id].append(time.time())
            debug_logger.log_info(f"Token {token_id} acquired image slot (remaining: {self._image_concurrency[token_id]})")
            return True

    async def acquire_video(self, token_id: int) -> bool:
        """
        Acquire video concurrency slot
        
        Args:
            token_id: Token ID
            
        Returns:
            True if acquired, False if not available
        """
        async with self._lock:
            # Expire stale slots before attempting to acquire
            self._expire_stale_slots(token_id)

            if token_id not in self._video_concurrency:
                # No limit — record timestamp anyway so TTL tracking is consistent
                if token_id not in self._video_acquired_at:
                    self._video_acquired_at[token_id] = []
                self._video_acquired_at[token_id].append(time.time())
                return True
            
            if self._video_concurrency[token_id] <= 0:
                return False

            self._video_concurrency[token_id] -= 1
            if token_id not in self._video_acquired_at:
                self._video_acquired_at[token_id] = []
            self._video_acquired_at[token_id].append(time.time())
            debug_logger.log_info(f"Token {token_id} acquired video slot (remaining: {self._video_concurrency[token_id]})")
            return True

    async def release_image(self, token_id: int):
        """
        Release image concurrency slot
        
        Args:
            token_id: Token ID
        """
        async with self._lock:
            stale_debt = self._image_stale_release_debt.get(token_id, 0)
            if stale_debt > 0:
                # This release belongs to a slot already force-released by TTL expiry.
                # Consume debt and avoid touching active counters/timestamps.
                self._image_stale_release_debt[token_id] = stale_debt - 1
                if self._image_stale_release_debt[token_id] <= 0:
                    self._image_stale_release_debt.pop(token_id, None)
                debug_logger.log_info(
                    f"Token {token_id} image release ignored; slot already reclaimed by TTL expiry"
                )
                return

            if token_id in self._image_concurrency:
                max_val = self._image_max.get(token_id, float('inf'))
                self._image_concurrency[token_id] = min(
                    self._image_concurrency[token_id] + 1,
                    int(max_val) if max_val != float('inf') else self._image_concurrency[token_id] + 1
                )
                debug_logger.log_info(f"Token {token_id} released image slot (remaining: {self._image_concurrency[token_id]})")
            # Pop the oldest acquisition timestamp (FIFO) to preserve acquisition order
            # and keep timestamp age aligned with slot lifetime for TTL expiry.
            if token_id in self._image_acquired_at and self._image_acquired_at[token_id]:
                self._image_acquired_at[token_id].pop(0)

    async def release_video(self, token_id: int):
        """
        Release video concurrency slot
        
        Args:
            token_id: Token ID
        """
        async with self._lock:
            stale_debt = self._video_stale_release_debt.get(token_id, 0)
            if stale_debt > 0:
                # This release belongs to a slot already force-released by TTL expiry.
                # Consume debt and avoid touching active counters/timestamps.
                self._video_stale_release_debt[token_id] = stale_debt - 1
                if self._video_stale_release_debt[token_id] <= 0:
                    self._video_stale_release_debt.pop(token_id, None)
                debug_logger.log_info(
                    f"Token {token_id} video release ignored; slot already reclaimed by TTL expiry"
                )
                return

            if token_id in self._video_concurrency:
                max_val = self._video_max.get(token_id, float('inf'))
                self._video_concurrency[token_id] = min(
                    self._video_concurrency[token_id] + 1,
                    int(max_val) if max_val != float('inf') else self._video_concurrency[token_id] + 1
                )
                debug_logger.log_info(f"Token {token_id} released video slot (remaining: {self._video_concurrency[token_id]})")
            # Pop the oldest acquisition timestamp (FIFO) to preserve acquisition order
            # and keep timestamp age aligned with slot lifetime for TTL expiry.
            if token_id in self._video_acquired_at and self._video_acquired_at[token_id]:
                self._video_acquired_at[token_id].pop(0)

    async def get_image_remaining(self, token_id: int) -> Optional[int]:
        """
        Get remaining image concurrency for token
        
        Args:
            token_id: Token ID
            
        Returns:
            Remaining count or None if no limit
        """
        async with self._lock:
            return self._image_concurrency.get(token_id)

    async def get_video_remaining(self, token_id: int) -> Optional[int]:
        """
        Get remaining video concurrency for token
        
        Args:
            token_id: Token ID
            
        Returns:
            Remaining count or None if no limit
        """
        async with self._lock:
            return self._video_concurrency.get(token_id)

    async def reset_token(self, token_id: int, image_concurrency: int = -1, video_concurrency: int = -1):
        """
        Reset concurrency counters for a token
        
        Args:
            token_id: Token ID
            image_concurrency: New image concurrency limit (-1 for no limit)
            video_concurrency: New video concurrency limit (-1 for no limit)
        """
        async with self._lock:
            if image_concurrency > 0:
                self._image_concurrency[token_id] = image_concurrency
                self._image_max[token_id] = image_concurrency
            elif token_id in self._image_concurrency:
                del self._image_concurrency[token_id]
                self._image_max.pop(token_id, None)
            
            if video_concurrency > 0:
                self._video_concurrency[token_id] = video_concurrency
                self._video_max[token_id] = video_concurrency
            elif token_id in self._video_concurrency:
                del self._video_concurrency[token_id]
                self._video_max.pop(token_id, None)

            # Clear acquisition timestamp lists so old timestamps don't cause spurious TTL expiry
            self._image_acquired_at.pop(token_id, None)
            self._video_acquired_at.pop(token_id, None)
            self._image_stale_release_debt.pop(token_id, None)
            self._video_stale_release_debt.pop(token_id, None)
            
            debug_logger.log_info(f"Token {token_id} concurrency reset (image: {image_concurrency}, video: {video_concurrency})")

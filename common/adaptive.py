"""Bộ điều chỉnh chất lượng & tốc độ khung hình tự động theo tải mạng/CPU thực tế."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BroadcastTier:
    """Một bậc cấu hình trình chiếu màn hình."""

    label: str
    width: int
    height: int
    fps: float
    quality: int


BROADCAST_TIERS: tuple[BroadcastTier, ...] = (
    BroadcastTier("HD mượt (1280×720, 10 FPS)", 1280, 720, 10.0, 65),
    BroadcastTier("Khá (1024×576, 8 FPS)", 1024, 576, 8.0, 56),
    BroadcastTier("Phòng đông 45-50 máy (960×540, 5 FPS)", 960, 540, 5.0, 48),
    BroadcastTier("Tiết kiệm tối đa (800×450, 3.5 FPS)", 800, 450, 3.5, 42),
)


class AdaptiveTierController:
    """Tự động hạ bậc khi có lag/timeout và tự nâng bậc khi mạng thông thoáng."""

    def __init__(
        self,
        tiers: tuple[BroadcastTier, ...] = BROADCAST_TIERS,
        initial_tier: int = 0,
        downgrade_threshold: int = 3,
        upgrade_threshold: int = 25,
    ) -> None:
        self.tiers = tiers
        self.tier_index = max(0, min(len(tiers) - 1, initial_tier))
        self.downgrade_threshold = max(1, downgrade_threshold)
        self.upgrade_threshold = max(1, upgrade_threshold)
        self._slow_streak = 0
        self._fast_streak = 0

    @property
    def current(self) -> BroadcastTier:
        return self.tiers[self.tier_index]

    def record_sample(self, frame_elapsed: float, timed_out_count: int) -> BroadcastTier | None:
        """Ghi nhận 1 chu kỳ gửi; trả về BroadcastTier mới nếu vừa đổi bậc."""
        target_interval = 1.0 / max(1.0, self.current.fps)
        is_slow = timed_out_count > 0 or frame_elapsed > (target_interval * 0.75)
        is_fast = timed_out_count == 0 and frame_elapsed < (target_interval * 0.40)

        if is_slow:
            self._slow_streak += 1
            self._fast_streak = 0
            if (
                self._slow_streak >= self.downgrade_threshold
                and self.tier_index < len(self.tiers) - 1
            ):
                self.tier_index += 1
                self._slow_streak = 0
                return self.current
            return None

        self._slow_streak = 0
        if is_fast:
            self._fast_streak += 1
            if self._fast_streak >= self.upgrade_threshold and self.tier_index > 0:
                self.tier_index -= 1
                self._fast_streak = 0
                return self.current
        else:
            self._fast_streak = 0
        return None

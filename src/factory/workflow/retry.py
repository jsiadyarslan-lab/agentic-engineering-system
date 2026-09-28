#!/usr/bin/env python3
"""
Retry Policy
Configurable retry logic with exponential backoff.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple, Type
import random


@dataclass
class RetryPolicy:
    """Configuration for retry behavior."""
    
    max_retries: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    exponential_base: float = 2.0
    jitter: bool = True
    retry_on: Tuple[Type[Exception], ...] = (
        ConnectionError,
        TimeoutError,
        IOError,
    )
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number."""
        delay = min(
            self.base_delay * (self.exponential_base ** attempt),
            self.max_delay
        )
        if self.jitter:
            import random
            delay *= (0.5 + random.random() * 0.5)
        return delay
    
    def should_retry(self, exception: Exception, attempt: int) -> bool:
        """Determine if an exception should trigger a retry."""
        if attempt >= self.max_retries:
            return False
        return isinstance(exception, self.retry_on)


# Import required modules
from dataclasses import dataclass, field
from typing import Tuple, Type
import random
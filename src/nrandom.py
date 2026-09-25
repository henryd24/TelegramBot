import random
from collections import Counter


def most_common_number(start: int, end: int, repetitions: int = 1000) -> tuple[int, int]:
    """
    Generate random numbers and return the most common one.

    Args:
        start (int): The lower bound of the random number range.
        end (int): The upper bound of the random number range.
        repetitions (int, optional): The number of random numbers to generate. Defaults to 1000.

    Returns:
        tuple: A tuple containing the most common number and its count.
    """
    low, high = (start, end) if start <= end else (end, start)
    reps = max(1, min(int(repetitions), 100_000))
    numbers = [random.randint(low, high) for _ in range(reps)]
    counter = Counter(numbers)
    return counter.most_common(1)[0]


import random
from collections import Counter

def most_common_number(start, end, repetitions=1000) -> tuple[int, int]:
    """
    Generate random numbers and return the most common one.

    Args:
        start (int): The lower bound of the random number range.
        end (int): The upper bound of the random number range.
        repetitions (int, optional): The number of random numbers to generate. Defaults to 1000.

    Returns:
        tuple: A tuple containing the most common number and its count.
    """
    numbers = [random.randint(start, end) for _ in range(repetitions)]
    counter = Counter(numbers)
    return counter.most_common(1)[0]

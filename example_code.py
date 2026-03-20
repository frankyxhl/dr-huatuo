"""
Example code - demonstrates Code Analyzer.
Contains some typical code quality issues.
"""


# Security issue: using eval
def run_expression(expr):
    """Evaluate an expression."""
    return eval(expr)


# Excessive complexity
def classify_user(age, income, score, level, region):
    """Classify user - too many branches."""
    if age < 18:
        if income < 1000:
            if score < 50:
                return "A1"
            else:
                return "A2"
        else:
            if score < 50:
                return "A3"
            else:
                return "A4"
    elif age < 30:
        if income < 2000:
            if level == 1:
                return "B1"
            elif level == 2:
                return "B2"
            else:
                return "B3"
        else:
            if region == "north":
                return "B4"
            else:
                return "B5"
    else:
        if income < 3000:
            return "C1"
        else:
            return "C2"


# Missing type annotations and documentation
def process(a, b, c):
    return a + b * c


# Duplicate code
def calc_tax(salary):
    base = salary * 0.1
    return base + 100


def calc_bonus(salary):
    base = salary * 0.1
    return base + 100


# Hardcoded password (security issue)
DB_PASSWORD = "admin123"


class DataProcessor:
    """Data processing class."""

    def __init__(self, name):
        self.name = name
        self.data = []

    def add(self, item):
        self.data.append(item)

    def get_average(self):
        if not self.data:
            return None
        return sum(self.data) / len(self.data)

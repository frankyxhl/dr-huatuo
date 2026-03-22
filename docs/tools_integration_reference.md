# Python 代码质量分析工具集成参考

本文档汇总了报告中提到的各工具的集成方式、输出格式和建议用法。

## 工具总览

| 工具 | 用途 | 输出格式 | 安装方式 |
|------|------|----------|----------|
| ruff | Lint + Format | JSON | pip install ruff |
| radon | 复杂度分析 | JSON | pip install radon |
| bandit | 安全扫描 | JSON | pip install bandit |
| mypy | 类型检查 | JSON/Text | pip install mypy |
| pylint | 全面 Lint | JSON | pip install pylint |
| pytest | 测试框架 | JUnit/TAP | pip install pytest |
| coverage | 覆盖率 | JSON/XML/HTML | pip install coverage pytest-cov |
| jscpd | 重复检测 | JSON | npm install -g jscpd |

---

## 1. Ruff (Lint + Format)

**特点**: 极快、支持自动修复、集成多个 linter

### 命令

```bash
# 检查并输出 JSON
ruff check <path> --output-format=json

# 检查并自动修复
ruff check <path> --fix

# 格式化代码
ruff format <path>
```

### 输出格式 (JSON)

```json
[
  {
    "cell": null,
    "code": "F401",              // 规则 ID
    "end_location": {"column": 14, "row": 1},
    "filename": "example.py",
    "fix": null,
    "location": {"column": 11, "row": 1},
    "message": "`os` imported but unused",
    "noqa_row": 1,
    "url": "https://docs.astral.sh/ruff/rules/unused-import"
  }
]
```

### Python 集成

```python
import subprocess
import json

def run_ruff(file_path: str) -> list[dict]:
    result = subprocess.run(
        ["ruff", "check", file_path, "--output-format=json"],
        capture_output=True, text=True
    )
    return json.loads(result.stdout) if result.stdout else []

# 使用
violations = run_ruff("example.py")
print(f"Found {len(violations)} violations")
```

---

## 2. Radon (复杂度分析)

**特点**: 计算圈复杂度、认知复杂度、可维护性指数

### 命令

```bash
# 圈复杂度 (JSON)
radon cc <path> -j

# 认知复杂度
radon cc <path> -s --total-average

# 可维护性指数
radon mi <path> -j
```

### 输出格式 (JSON)

```json
{
  "example.py": [
    {
      "type": "function",
      "rank": "B",           // A=简单, F=极复杂
      "endline": 20,
      "name": "process_data",
      "lineno": 5,
      "complexity": 8,       // 圈复杂度数值
      "col_offset": 0,
      "closures": []
    }
  ]
}
```

### Python 集成

```python
import subprocess
import json

def get_complexity(file_path: str) -> dict:
    result = subprocess.run(
        ["radon", "cc", file_path, "-j"],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)

def get_max_complexity(data: dict, file_path: str) -> int:
    functions = data.get(file_path, [])
    return max((f["complexity"] for f in functions), default=0)
```

---

## 3. Bandit (安全扫描)

**特点**: 专门针对 Python 的安全 linter

### 命令

```bash
# 扫描并输出 JSON
bandit -r <path> -f json -o bandit.json

# 只显示高危问题
bandit -r <path> -ll  # 只显示 medium/high
```

### 输出格式 (JSON)

```json
{
  "results": [
    {
      "code": "14 def run(expr):\n15     return eval(expr)\n",
      "col_offset": 11,
      "filename": "example.py",
      "issue_confidence": "HIGH",
      "issue_cwe": {"id": 78, "link": "https://..."},
      "issue_severity": "MEDIUM",
      "issue_text": "Use of possibly insecure function",
      "line_number": 15,
      "test_id": "B307",
      "test_name": "blacklist"
    }
  ]
}
```

### Python 集成

```python
import subprocess
import json

def run_bandit(file_path: str) -> list[dict]:
    result = subprocess.run(
        ["bandit", "-r", file_path, "-f", "json"],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    return data.get("results", [])

def count_severity(issues: list[dict]) -> dict:
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for issue in issues:
        sev = issue.get("issue_severity", "LOW")
        counts[sev] = counts.get(sev, 0) + 1
    return counts
```

---

## 4. Mypy (类型检查)

**特点**: 静态类型检查、支持严格模式

### 命令

```bash
# 基本检查
mypy <path> --output=json

# 严格模式
mypy <path> --strict --output=json

# 只检查未标注函数
mypy <path> --disallow-untyped-defs --output=json
```

### 输出格式 (JSON Lines)

```json
{"file": "example.py", "severity": "error", "message": "Function is missing a type annotation", "line": 3, "column": 0, "error_code": "no-untyped-def"}
```

### Python 集成

```python
import subprocess
import json

def run_mypy(file_path: str, strict: bool = False) -> list[dict]:
    cmd = ["mypy", file_path, "--output=json"]
    if strict:
        cmd.append("--strict")
    result = subprocess.run(cmd, capture_output=True, text=True)
    errors = []
    for line in result.stdout.strip().split("\n"):
        if line:
            errors.append(json.loads(line))
    return errors
```

---

## 5. Pylint (全面 Lint)

**特点**: 最全面的 Python linter、包含重复检测

### 命令

```bash
# 输出 JSON
pylint <path> --output-format=json

# 输出评分
pylint <path> --output-format=parseable

# 只检测重复代码
pylint <path> --disable=all --enable=R0801 --min-similarity-lines=4
```

### 输出格式 (JSON)

```json
[
  {
    "type": "convention",
    "module": "example",
    "obj": "func_name",
    "line": 5,
    "column": 0,
    "path": "example.py",
    "symbol": "missing-function-docstring",
    "message": "Missing function or method docstring",
    "message-id": "C0116"
  }
]
```

### Python 集成

```python
import subprocess
import json
import re

def run_pylint(file_path: str) -> list[dict]:
    result = subprocess.run(
        ["pylint", file_path, "--output-format=json"],
        capture_output=True, text=True
    )
    return json.loads(result.stdout) if result.stdout else []

def get_pylint_score(file_path: str) -> float:
    result = subprocess.run(
        ["pylint", file_path, "--output-format=parseable"],
        capture_output=True, text=True
    )
    match = re.search(r"rated at ([\d.]+)/10", result.stdout)
    return float(match.group(1)) if match else 0.0
```

---

## 6. Pytest + Coverage (测试与覆盖率)

**特点**: Python 标准测试框架、覆盖率集成

### 命令

```bash
# 运行测试并生成覆盖率
pytest <path> --cov=<module> --cov-report=json --cov-report=term-missing

# 只生成 JSON 报告
pytest <path> --cov=<module> --cov-report=json:coverage.json
```

### 覆盖率 JSON 格式

```json
{
  "meta": {
    "version": "7.13.5",
    "timestamp": "2026-03-19T..."
  },
  "files": {
    "example.py": {
      "executed_lines": [1, 2, 3, 5, 6],
      "missing_lines": [10, 11],
      "summary": {
        "covered_lines": 5,
        "num_statements": 7,
        "percent_covered": 71.43
      }
    }
  },
  "totals": {
    "covered_lines": 51,
    "num_statements": 61,
    "percent_covered": 83.61
  }
}
```

### Python 集成

```python
import subprocess
import json

def run_tests_with_coverage(test_path: str, module_path: str) -> dict:
    result = subprocess.run(
        ["pytest", test_path, f"--cov={module_path}", "--cov-report=json:coverage.json", "-q"],
        capture_output=True, text=True
    )
    with open("coverage.json") as f:
        return json.load(f)

def get_coverage_percent(data: dict, file_path: str) -> float:
    file_data = data["files"].get(file_path, {})
    return file_data.get("summary", {}).get("percent_covered", 0.0)
```

---

## 7. JSCPD (重复代码检测)

**特点**: 支持 150+ 语言、基于 token 的检测

### 命令

```bash
# 检测重复代码
jscpd <path> --reporters json --output . --min-lines 3 --min-tokens 20

# 查看报告
cat jscpd-report.json
```

### 输出格式 (JSON)

```json
{
  "statistics": {
    "total": {
      "lines": 100,
      "clones": 2,
      "duplicatedLines": 10,
      "percentage": 10
    }
  },
  "duplicates": [
    {
      "format": "python",
      "lines": 5,
      "fragment": "(x):\n    y = x * 0.1\n    return y + 1",
      "firstFile": {
        "name": "a.py",
        "start": 3,
        "end": 7
      },
      "secondFile": {
        "name": "b.py",
        "start": 11,
        "end": 15
      }
    }
  ]
}
```

### Python 集成

```python
import subprocess
import json

def detect_duplicates(path: str, min_lines: int = 3) -> dict:
    subprocess.run(
        ["npx", "jscpd", path, "--reporters", "json", "--output", ".",
         "--min-lines", str(min_lines)],
        capture_output=True
    )
    with open("jscpd-report.json") as f:
        return json.load(f)

def get_duplication_stats(data: dict) -> dict:
    stats = data.get("statistics", {}).get("total", {})
    return {
        "total_lines": stats.get("lines", 0),
        "clones": stats.get("clones", 0),
        "duplicated_lines": stats.get("duplicatedLines", 0),
        "percentage": stats.get("percentage", 0)
    }
```

---

## 统一分析器接口设计

```python
from dataclasses import dataclass
from typing import Optional
import subprocess
import json


@dataclass
class CodeMetrics:
    """统一的代码指标结构"""
    file_path: str
    
    # 复杂度
    max_cyclomatic_complexity: int = 0
    avg_cyclomatic_complexity: float = 0.0
    
    # Lint
    ruff_violations: int = 0
    pylint_score: float = 0.0
    
    # 类型
    mypy_errors: int = 0
    
    # 安全
    bandit_high: int = 0
    bandit_medium: int = 0
    
    # 覆盖率
    line_coverage: float = 0.0
    branch_coverage: float = 0.0
    
    # 重复
    duplicate_blocks: int = 0
    duplicate_percentage: float = 0.0


class CodeAnalyzer:
    """统一代码分析器"""
    
    def __init__(self, venv_path: str = ".venv"):
        self.venv_path = venv_path
    
    def analyze(self, file_path: str) -> CodeMetrics:
        """对单个文件运行所有分析"""
        metrics = CodeMetrics(file_path=file_path)
        
        # 并行运行各工具
        metrics.max_cyclomatic_complexity = self._run_radon(file_path)
        metrics.ruff_violations = len(self._run_ruff(file_path))
        metrics.pylint_score = self._run_pylint(file_path)
        metrics.mypy_errors = len(self._run_mypy(file_path))
        
        bandit_results = self._run_bandit(file_path)
        metrics.bandit_high = sum(1 for r in bandit_results if r.get("issue_severity") == "HIGH")
        metrics.bandit_medium = sum(1 for r in bandit_results if r.get("issue_severity") == "MEDIUM")
        
        return metrics
    
    def _run_ruff(self, file_path: str) -> list:
        result = subprocess.run(
            ["ruff", "check", file_path, "--output-format=json"],
            capture_output=True, text=True
        )
        return json.loads(result.stdout) if result.stdout else []
    
    def _run_radon(self, file_path: str) -> int:
        result = subprocess.run(
            ["radon", "cc", file_path, "-j"],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout) if result.stdout else {}
        functions = data.get(file_path, [])
        return max((f["complexity"] for f in functions), default=0)
    
    def _run_pylint(self, file_path: str) -> float:
        result = subprocess.run(
            ["pylint", file_path, "--output-format=parseable"],
            capture_output=True, text=True
        )
        import re
        match = re.search(r"rated at ([\d.]+)/10", result.stdout + result.stderr)
        return float(match.group(1)) if match else 0.0
    
    def _run_mypy(self, file_path: str) -> list:
        result = subprocess.run(
            ["mypy", file_path, "--output=json", "--no-error-summary"],
            capture_output=True, text=True
        )
        errors = []
        for line in result.stdout.strip().split("\n"):
            if line:
                errors.append(json.loads(line))
        return errors
    
    def _run_bandit(self, file_path: str) -> list:
        result = subprocess.run(
            ["bandit", "-r", file_path, "-f", "json"],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout) if result.stdout else {}
        return data.get("results", [])


# 使用示例
if __name__ == "__main__":
    analyzer = CodeAnalyzer()
    metrics = analyzer.analyze("test_samples/bad_code.py")
    print(f"复杂度: {metrics.max_cyclomatic_complexity}")
    print(f"Ruff违规: {metrics.ruff_violations}")
    print(f"Pylint评分: {metrics.pylint_score}")
    print(f"Mypy错误: {metrics.mypy_errors}")
    print(f"Bandit高危: {metrics.bandit_high}")
```

---

## 推荐的集成策略

### 1. 预筛选阶段 (快速)
```python
# 只运行快速工具
ruff violations + radon complexity
# 阈值: ruff violations < 5, complexity < 10
```

### 2. 深度分析阶段 (中等)
```python
# 加入安全检查和类型检查
+ bandit security + mypy types
# 阈值: bandit high = 0, mypy errors < 3
```

### 3. 完整分析阶段 (慢速)
```python
# 加入测试和覆盖率
+ pytest + coverage
# 阈值: coverage > 80%, all tests pass
```

---

## 性能建议

| 工具 | 相对速度 | 建议用法 |
|------|----------|----------|
| ruff | 极快 | 所有样本 |
| radon | 快 | 所有样本 |
| bandit | 中等 | 所有样本 |
| mypy | 慢 | 抽样或高价值样本 |
| pylint | 慢 | 抽样或高价值样本 |
| pytest + coverage | 最慢 | 仅对有测试的样本 |
| jscpd | 中等 | 项目级，非单文件 |

---

## 质量标签映射

| 质量维度 | 主要工具 | 辅助工具 | 关键指标 |
|----------|----------|----------|----------|
| 正确性 | pytest | - | 测试通过率 |
| 可读性 | ruff | pylint | PEP8违规数 |
| 复杂度 | radon | pylint | 圈复杂度 |
| 类型一致性 | mypy | pyright | 类型错误数 |
| 安全性 | bandit | sonarqube | 高危漏洞数 |
| 可维护性 | pylint | jscpd | 重复百分比 |
| 测试充分性 | coverage | pytest | 覆盖率百分比 |

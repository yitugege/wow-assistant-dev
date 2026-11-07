"""独立源码程序的资源入口；不加载原业务EXE或SDK。"""
from dataclasses import dataclass
import json
from pathlib import Path

from .pipeline import DecisionPipeline


@dataclass(frozen=True)
class Assets:
    directory: Path
    contract: dict
    readable_contract: dict
    rules: dict
    readable_rules: dict

    @classmethod
    def load(cls, directory: Path):
        directory = Path(directory)
        documents = []
        for name in ("contract.json", "contract_readable.json", "rules.json", "rules_readable.json"):
            value = json.loads((directory / name).read_bytes())
            if not isinstance(value, dict):
                raise ValueError(f"资源不是JSON对象：{name}")
            documents.append(value)
        return cls(directory, *documents)

    def pipeline(self):
        return DecisionPipeline(self.contract, self.readable_contract, self.rules, self.readable_rules)

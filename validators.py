"""데모 모드 등에서 쓰는 작은 도우미"""
from extractor import validate_extraction


def extraction_issues(agent):
    if agent.extracted is None:
        return []
    return [i for i in validate_extraction(agent.extracted) if "흐리게" not in i]

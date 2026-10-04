"""Conservative, configurable airline recognition without an LLM or database call."""

import re
from pathlib import Path

import yaml
from qdrant_client.models import FieldCondition, Filter, MatchAny


CATALOG = Path(__file__).resolve().parents[1] / 'config' / 'airline_aliases.yaml'


def airline_filter(query):
    """Restrict explicit recognized names; general/unknown questions stay semantic.

    Multiple airlines use OR semantics. This does not guarantee balanced evidence
    for comparisons. Exclusion wording disables automatic filtering.
    """
    if re.search(r'\b(?:not|except|excluding|other than|instead of)\b', query, re.IGNORECASE):
        return None
    catalog = yaml.safe_load(CATALOG.read_text(encoding='utf-8'))['airlines']
    values = set()
    for canonical, aliases in catalog.items():
        names = [canonical, *aliases]
        if any(re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', query, re.IGNORECASE)
               for name in names):
            for name in names:
                values.update((name, name.lower(), name.upper(), name.title()))
    if not values:
        return None
    return Filter(must=[FieldCondition(key='airline_name', match=MatchAny(any=sorted(values)))])

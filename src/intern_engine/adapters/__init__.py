"""Adapter registry."""

from __future__ import annotations

from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter
from .ashby import AshbyAdapter
from .smartrecruiters import SmartRecruitersAdapter
from .workday import WorkdayAdapter
from .adzuna import AdzunaAdapter
from .phenom import PhenomAdapter
from .amazonjobs import AmazonJobsAdapter

REGISTRY = {
    a.name: a
    for a in (
        GreenhouseAdapter(),
        LeverAdapter(),
        AshbyAdapter(),
        SmartRecruitersAdapter(),
        WorkdayAdapter(),
        AdzunaAdapter(),
        PhenomAdapter(),
        AmazonJobsAdapter(),
    )
}


def get_adapter(name: str):
    return REGISTRY.get(name)

from __future__ import annotations

from django import forms
from django.conf import settings

from research.models import ResearchTask


class ResearchTaskForm(forms.Form):
    question = forms.CharField(
        max_length=4000,
        label="研究问题",
        widget=forms.Textarea(
            attrs={"rows": 4, "placeholder": "例如：PostgreSQL 的索引类型分别适合什么场景？"}
        ),
    )
    strategy = forms.ChoiceField(
        choices=ResearchTask.STRATEGY_CHOICES,
        initial=ResearchTask.STRATEGY_AGENT,
        label="策略",
    )
    max_steps = forms.IntegerField(
        min_value=3,
        max_value=30,
        initial=settings.RESEARCH_MAX_STEPS,
        required=False,
        label="最大步数",
    )
    offline = forms.BooleanField(required=False, label="仅使用本地书签（离线）")

    def to_options(self) -> dict:
        return {"offline": bool(self.cleaned_data.get("offline"))}

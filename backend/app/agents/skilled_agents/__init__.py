"""Skilled agents — the agents that produce triage output.

Each agent is declared here with its identity and contract; the integration
code goes inside each agent's own module. Nothing in this package knows about
graphs or routing, so the same agents can be composed into any number of
workflows under `app.graph_workflow`.

Declared in the order a triage workflow would normally reach for them
(`app.agents.support_agents` prepares Corti access first):

    referral_document_reader
      -> referral_document_classifier
      -> case_data_extractor
      -> case_summariser
      -> urgency_assessor + clinical_flag_detector
      -> next_action_recommender
"""

from app.agents.base import Agent
from app.agents.skilled_agents.case_data_extractor import CaseDataExtractor
from app.agents.skilled_agents.case_summariser import CaseSummariser
from app.agents.skilled_agents.clinical_flag_detector import ClinicalFlagDetector
from app.agents.skilled_agents.next_action_recommender import NextActionRecommender
from app.agents.skilled_agents.pre_consultation_briefer import PreConsultationBriefer
from app.agents.skilled_agents.referral_document_classifier import (
    ReferralDocumentClassifier,
)
from app.agents.skilled_agents.referral_document_reader import ReferralDocumentReader
from app.agents.skilled_agents.urgency_assessor import UrgencyAssessor

# Worker agents, declared in the expected pipeline order.
WORKER_CLASSES: tuple[type[Agent], ...] = (
    ReferralDocumentReader,
    ReferralDocumentClassifier,
    CaseDataExtractor,
    CaseSummariser,
    UrgencyAssessor,
    ClinicalFlagDetector,
    NextActionRecommender,
    PreConsultationBriefer,
)

__all__ = [
    "WORKER_CLASSES",
    "CaseDataExtractor",
    "CaseSummariser",
    "ClinicalFlagDetector",
    "NextActionRecommender",
    "PreConsultationBriefer",
    "ReferralDocumentClassifier",
    "ReferralDocumentReader",
    "UrgencyAssessor",
]

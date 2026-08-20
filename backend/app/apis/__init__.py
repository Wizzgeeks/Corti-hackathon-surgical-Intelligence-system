from fastapi import APIRouter

from app.apis.agent_runs import router as agent_runs_router
from app.apis.appointments import router as appointments_router
from app.apis.auth import router as auth_router
from app.apis.case_analysis import router as case_analysis_router
from app.apis.cases import router as cases_router
from app.apis.consultations import router as consultations_router
from app.apis.contacts import router as contacts_router
from app.apis.investigations import router as investigations_router
from app.apis.questionnaire import router as questionnaire_router
from app.apis.referrals import router as referrals_router
from app.apis.teams import router as teams_router
from app.apis.today import router as today_router

api_router = APIRouter()
api_router.include_router(referrals_router)
api_router.include_router(cases_router)
api_router.include_router(case_analysis_router)
api_router.include_router(agent_runs_router)
api_router.include_router(appointments_router)
api_router.include_router(consultations_router)
api_router.include_router(teams_router)
api_router.include_router(today_router)
api_router.include_router(contacts_router)
api_router.include_router(investigations_router)
api_router.include_router(questionnaire_router)
api_router.include_router(auth_router)

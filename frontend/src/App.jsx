import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './Layout.jsx'
import MyMorning from './pages/MyMorning.jsx'
import MyEvening from './pages/MyEvening.jsx'
import Appointments from './pages/Appointments.jsx'
import Cases from './pages/Cases.jsx'
import CaseDetail from './pages/CaseDetail.jsx'
import Team from './pages/Team.jsx'
import Contacts from './pages/Contacts.jsx'
import NewReferral from './pages/NewReferral.jsx'
import PatientQuestionnaire from './pages/PatientQuestionnaire.jsx'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Outside the app layout on purpose: a patient opening this link
            gets the questionnaire and nothing else — no nav, no case data. */}
        <Route
          path="questionnaire/:caseId"
          element={<PatientQuestionnaire />}
        />

        <Route element={<Layout />}>
          <Route index element={<Navigate to="/morning" replace />} />
          <Route path="morning" element={<MyMorning />} />
          {/* The page was called "today" before it was split in two. */}
          <Route path="today" element={<Navigate to="/morning" replace />} />
          <Route path="evening" element={<MyEvening />} />
          <Route path="appointments" element={<Appointments />} />
          <Route path="cases" element={<Cases />} />
          {/* Declared before ":id" so "new" is not read as a case id. */}
          <Route path="cases/new" element={<CaseDetail isNew />} />
          <Route path="cases/:id" element={<CaseDetail />} />
          <Route path="team" element={<Team />} />
          <Route path="contacts" element={<Contacts />} />
          <Route path="referrals/new" element={<NewReferral />} />
          <Route path="*" element={<Navigate to="/morning" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App

import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './Layout.jsx'
import MyToday from './pages/MyToday.jsx'
import Appointments from './pages/Appointments.jsx'
import Cases from './pages/Cases.jsx'
import CaseDetail from './pages/CaseDetail.jsx'
import Team from './pages/Team.jsx'
import Contacts from './pages/Contacts.jsx'
import NewReferral from './pages/NewReferral.jsx'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/today" replace />} />
          <Route path="today" element={<MyToday />} />
          <Route path="appointments" element={<Appointments />} />
          <Route path="cases" element={<Cases />} />
          {/* Declared before ":id" so "new" is not read as a case id. */}
          <Route path="cases/new" element={<CaseDetail isNew />} />
          <Route path="cases/:id" element={<CaseDetail />} />
          <Route path="team" element={<Team />} />
          <Route path="contacts" element={<Contacts />} />
          <Route path="referrals/new" element={<NewReferral />} />
          <Route path="*" element={<Navigate to="/today" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App

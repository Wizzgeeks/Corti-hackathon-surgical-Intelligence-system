import { useCallback, useEffect, useState } from 'react'
import {
  createTeam,
  deleteTeam,
  listTeams,
  updateTeam,
} from '../lib/api.js'

const BLANK = { name: '', speciality: '', description: '' }

function Team() {
  const [teams, setTeams] = useState(null)
  const [error, setError] = useState('')
  // null = form closed; otherwise the team being edited (blank for a new one).
  const [form, setForm] = useState(null)

  const load = useCallback(
    () =>
      listTeams()
        .then((data) => {
          setError('')
          setTeams(data.teams)
        })
        .catch((exc) => setError(exc.message)),
    [],
  )

  useEffect(() => {
    load()
  }, [load])

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    try {
      if (form.consultant_team_id) {
        await updateTeam(form.consultant_team_id, {
          name: form.name,
          speciality: form.speciality,
          description: form.description,
        })
      } else {
        await createTeam(form)
      }
      setForm(null)
      await load()
    } catch (exc) {
      setError(exc.message)
    }
  }

  const remove = async (team) => {
    if (!window.confirm(`Delete ${team.name}?`)) return
    setError('')
    try {
      await deleteTeam(team.consultant_team_id)
      await load()
    } catch (exc) {
      // The API refuses while cases or appointments still reference the team.
      setError(exc.message)
    }
  }

  if (!teams && !error) return null

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Consultant teams</h2>
        {!form && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setForm({ ...BLANK })}
          >
            Add team
          </button>
        )}
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      {form && (
        <form className="inline-form" onSubmit={submit}>
          <div className="edit-list inline-form-fields">
            <div className="edit-field">
              <label className="field-label" htmlFor="team-name">
                Name
              </label>
              <input
                id="team-name"
                className="input"
                value={form.name}
                required
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div className="edit-field">
              <label className="field-label" htmlFor="team-speciality">
                Speciality
              </label>
              <input
                id="team-speciality"
                className="input"
                value={form.speciality}
                onChange={(e) =>
                  setForm({ ...form, speciality: e.target.value })
                }
              />
            </div>
            <div className="edit-field">
              <label className="field-label" htmlFor="team-description">
                Description
              </label>
              <input
                id="team-description"
                className="input"
                value={form.description}
                onChange={(e) =>
                  setForm({ ...form, description: e.target.value })
                }
              />
            </div>
          </div>
          <div className="form-actions">
            <button type="button" className="btn" onClick={() => setForm(null)}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary">
              {form.consultant_team_id ? 'Save team' : 'Create team'}
            </button>
          </div>
        </form>
      )}

      {teams?.length === 0 ? (
        <p>No consultant teams yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Team</th>
                <th scope="col">Speciality</th>
                <th scope="col">Description</th>
                <th scope="col" className="col-actions">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {(teams ?? []).map((team) => (
                <tr key={team.consultant_team_id}>
                  <td className="cell-strong">{team.name}</td>
                  <td>{team.speciality || '—'}</td>
                  <td className="cell-wrap">{team.description || '—'}</td>
                  <td className="col-actions">
                    <div className="row-actions">
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => setForm({ ...team })}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-danger"
                        onClick={() => remove(team)}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export default Team

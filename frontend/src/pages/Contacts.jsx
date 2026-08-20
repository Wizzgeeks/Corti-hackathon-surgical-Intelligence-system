import { useCallback, useEffect, useState } from 'react'
import {
  createContact,
  deleteContact,
  listContacts,
  updateContact,
} from '../lib/api.js'

const BLANK = { name: '', role: '', organization: '' }

function Contacts() {
  const [contacts, setContacts] = useState(null)
  const [error, setError] = useState('')
  // null = form closed; otherwise the contact being edited (blank for a new one).
  const [form, setForm] = useState(null)

  const load = useCallback(
    () =>
      listContacts()
        .then((data) => {
          setError('')
          setContacts(data.contacts)
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
      if (form.contact_id) {
        await updateContact(form.contact_id, {
          name: form.name,
          role: form.role,
          organization: form.organization,
        })
      } else {
        await createContact(form)
      }
      setForm(null)
      await load()
    } catch (exc) {
      // A duplicate name at the same organization comes back as a 409.
      setError(exc.message)
    }
  }

  const remove = async (contact) => {
    if (!window.confirm(`Delete ${contact.name}?`)) return
    setError('')
    try {
      await deleteContact(contact.contact_id)
      await load()
    } catch (exc) {
      setError(exc.message)
    }
  }

  if (!contacts && !error) return null

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Contacts</h2>
        {!form && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setForm({ ...BLANK })}
          >
            Add contact
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
              <label className="field-label" htmlFor="contact-name">
                Name
              </label>
              <input
                id="contact-name"
                className="input"
                placeholder="Dr Aisha Khan"
                value={form.name}
                required
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div className="edit-field">
              <label className="field-label" htmlFor="contact-role">
                Role
              </label>
              <input
                id="contact-role"
                className="input"
                placeholder="GP"
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
              />
            </div>
            <div className="edit-field">
              <label className="field-label" htmlFor="contact-organization">
                Organization
              </label>
              <input
                id="contact-organization"
                className="input"
                value={form.organization}
                onChange={(e) =>
                  setForm({ ...form, organization: e.target.value })
                }
              />
            </div>
          </div>
          <div className="form-actions">
            <button type="button" className="btn" onClick={() => setForm(null)}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary">
              {form.contact_id ? 'Save contact' : 'Create contact'}
            </button>
          </div>
        </form>
      )}

      {contacts?.length === 0 ? (
        <p>No contacts yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Role</th>
                <th scope="col">Organization</th>
                <th scope="col" className="col-actions">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {(contacts ?? []).map((contact) => (
                <tr key={contact.contact_id}>
                  <td className="cell-strong">{contact.name}</td>
                  <td>{contact.role || '—'}</td>
                  <td>{contact.organization || '—'}</td>
                  <td className="col-actions">
                    <div className="row-actions">
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => setForm({ ...contact })}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-danger"
                        onClick={() => remove(contact)}
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

export default Contacts

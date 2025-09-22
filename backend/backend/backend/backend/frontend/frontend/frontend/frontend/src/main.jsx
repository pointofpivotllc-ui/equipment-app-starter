import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'

const API = (path) => (import.meta.env.VITE_API || 'http://localhost:8000') + path

function App() {
  const [token, setToken] = useState('')
  const [email, setEmail] = useState('admin@example.com')
  const [password, setPassword] = useState('admin123')

  const [number, setNumber] = useState('TRK-1001')
  const [desc, setDesc] = useState('Bucket truck model X')
  const [type, setType] = useState('Bucket Truck')
  const [job, setJob] = useState('JOB-42')
  const [mileage, setMileage] = useState(120345)

  const [areas, setAreas] = useState([
    { area_code: 'DIELECTRIC', applies: true, last_date: '', notes: '' },
    { area_code: 'DOT_ANNUAL', applies: true, last_date: '', notes: '' },
    { area_code: 'CHASSIS_PM', applies: true, last_date: '', notes: '' },
  ])

  const [locked, setLocked] = useState(false)
  const [editable, setEditable] = useState(false)
  const [lockMsg, setLockMsg] = useState('')

  const login = async () => {
    const res = await fetch(API('/auth/login'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    })
    if (!res.ok) { alert('Login failed'); return }
    const data = await res.json()
    setToken(data.token)
  }

  const lock = async () => {
    const form = new FormData()
    form.append('number', number)
    const res = await fetch(API('/equipment/lock'), {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: form
    })
    const data = await res.json()
    if (data.locked) {
      setLocked(true)
      setEditable(!!data.editable)
      setLockMsg(data.editable ? 'You have the lock' : 'Locked by another user')
    } else {
      setLockMsg('Failed to lock')
    }
  }

  const release = async () => {
    const form = new FormData()
    form.append('number', number)
    await fetch(API('/equipment/release-lock'), {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: form
    })
    setLocked(false)
    setEditable(false)
  }

  const submit = async () => {
    const payload = {
      number,
      description: desc,
      type,
      job,
      mileage,
      tests: areas.map(a => ({
        area_code: a.area_code,
        applies: a.applies,
        last_date: a.last_date ? new Date(a.last_date).toISOString() : null,
        notes: a.notes || null
      }))
    }
    const res = await fetch(API('/equipment/upsert'), {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    })
    if (!res.ok) {
      const t = await res.text()
      alert('Save failed: ' + t)
      return
    }
    alert('Saved & lock released')
    setLocked(false)
    setEditable(false)
  }

  const upload = async (file, area_code) => {
    const form = new FormData()
    form.append('number', number)
    form.append('area_code', area_code)
    form.append('file', file)
    const res = await fetch(API('/attachments/upload'), {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: form
    })
    if (!res.ok) {
      alert('Upload failed')
    } else {
      alert('Uploaded')
    }
  }

  return (
    <div style={{ maxWidth: 800, margin: '30px auto', fontFamily: 'sans-serif' }}>
      <h1>Equipment App</h1>

      {!token && (
        <div style={{ border: '1px solid #ccc', padding: 16, borderRadius: 8 }}>
          <h3>Login</h3>
          <div>
            <label>Email</label><br/>
            <input value={email} onChange={e=>setEmail(e.target.value)} />
          </div>
          <div>
            <label>Password</label><br/>
            <input type="password" value={password} onChange={e=>setPassword(e.target.value)} />
          </div>
          <button onClick={login}>Login</button>
        </div>
      )}

      {token && (
        <div style={{ border: '1px solid #ccc', padding: 16, borderRadius: 8, marginTop: 16 }}>
          <h3>Enter Equipment</h3>
          <div>
            <label>Equipment Number</label><br/>
            <input value={number} onChange={e=>setNumber(e.target.value)} />
            {!locked ? <button onClick={lock} style={{ marginLeft: 8 }}>Lock</button> : <button onClick={release} style={{ marginLeft: 8 }}>Release</button>}
            <span style={{ marginLeft: 8, color: editable ? 'green' : 'red' }}>{lockMsg}</span>
          </div>
          <div>
            <label>Description</label><br/>
            <input value={desc} onChange={e=>setDesc(e.target.value)} disabled={!editable}/>
          </div>
          <div>
            <label>Type</label><br/>
            <select value={type} onChange={e=>setType(e.target.value)} disabled={!editable}>
              <option>Bucket Truck</option>
              <option>Digger Derrick</option>
              <option>Truck</option>
              <option>Trailer</option>
            </select>
          </div>
          <div>
            <label>Job</label><br/>
            <input value={job} onChange={e=>setJob(e.target.value)} disabled={!editable}/>
          </div>
          <div>
            <label>Mileage</label><br/>
            <input type="number" value={mileage} onChange={e=>setMileage(parseInt(e.target.value||'0'))} disabled={!editable}/>
          </div>

          <h4>Testing Areas</h4>
          {areas.map((a, idx) => (
            <div key={a.area_code} style={{ border: '1px solid #eee', padding: 12, borderRadius: 6, marginBottom: 8 }}>
              <div><b>{a.area_code}</b></div>
              <div>
                <label>Applies? </label>
                <input type="checkbox" checked={a.applies} onChange={e => {
                  const copy = [...areas]; copy[idx].applies = e.target.checked; setAreas(copy)
                }} disabled={!editable}/>
              </div>
              <div>
                <label>Last Date</label><br/>
                <input type="date" value={a.last_date} onChange={e => {
                  const copy = [...areas]; copy[idx].last_date = e.target.value; setAreas(copy)
                }} disabled={!editable}/>
              </div>
              <div>
                <label>Notes</label><br/>
                <input value={a.notes} onChange={e => {
                  const copy = [...areas]; copy[idx].notes = e.target.value; setAreas(copy)
                }} disabled={!editable}/>
              </div>
              <div>
                <label>Attachment</label><br/>
                <input type="file" onChange={e => upload(e.target.files[0], a.area_code)} disabled={!editable}/>
              </div>
            </div>
          ))}

          <button onClick={submit} disabled={!editable}>Submit</button>
        </div>
      )}
    </div>
  )
}

createRoot(document.getElementById('root')).render(<App />)

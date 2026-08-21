/** Figures for the two day pages.
 *
 *  Deliberately static: these screens are shown rather than operated, and a
 *  demo that pauses on a network call reads as broken. Nothing here reaches
 *  the API — swap this file for the `/today` endpoint when the pages need to
 *  be real.
 */

export const CONSULTANT = {
  name: 'Mr Ram Chandru',
  speciality: 'Hand & wrist surgery',
  clinic: 'Merivale Hand Clinic',
}

/* --- the day, as numbers -------------------------------------------------- */

/** The four types every patient today falls into. They sum to the headline,
 *  so the split can be read as a whole rather than as four loose counts. */
export const MIX = [
  { key: 'new', label: 'New patients', value: 8 },
  { key: 'follow_up', label: 'Follow-ups', value: 7 },
  { key: 'tele', label: 'Teleconsultations', value: 5 },
  { key: 'post_surgery', label: 'Post-surgery follow-ups', value: 4 },
]

export const PATIENTS_TODAY = MIX.reduce((sum, item) => sum + item.value, 0)

/** Everything else worth a number. `unit` is rendered small beside the
 *  figure; `tone` lifts the ones that should not be scanned past. */
export const KPIS = []

/* --- the evening ---------------------------------------------------------- */

/** What became of the patients who were consulted. The three sum to the
 *  headline — every patient seen left by one of these doors — which is why
 *  they are read together rather than as three loose counts. */
export const OUTCOMES = [
  { key: 'surgery', label: 'Booked for surgery', value: 6 },
  { key: 'imaging', label: 'Booked for imaging', value: 5 },
  { key: 'discharged', label: 'Discharged', value: 11 },
]

export const PATIENTS_CONSULTED = OUTCOMES.reduce(
  (sum, item) => sum + item.value,
  0,
)

/** The two figures that sit outside that arithmetic: the patients who never
 *  arrived, and the work the day did not finish. Both want a decision, so
 *  neither is left to be scanned past. */
export const EVENING_EXCEPTIONS = [
  { key: 'dna', label: 'Did not attend', value: 2, tone: 'warn' },
  { key: 'actions', label: 'Actions remaining', value: 2, tone: 'alert' },
]

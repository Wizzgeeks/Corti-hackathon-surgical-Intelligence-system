/** Display helper shared by the case pages. */

export const initials = (name) =>
  String(name ?? '')
    .split(' ')
    .map((part) => part[0])
    .slice(0, 2)
    .join('')

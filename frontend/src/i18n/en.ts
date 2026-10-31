import type { Messages } from './core'

/** English messages: must mirror zh.ts key for key (the type checker enforces it). */
export const en: Messages = {
  brand: {
    name: 'Inkreel',
    tagline: 'From ink to reel',
  },
  common: {
    cancel: 'Cancel',
    close: 'Close',
    retry: 'Retry',
    loading: 'Loading…',
    help: 'What is this?',
  },
  theme: { label: 'Theme', system: 'System', light: 'Light', dark: 'Dark' },
  lang: { label: 'Language' },
  shell: {
    newNovel: 'New novel',
    openLocal: 'Open local JSON',
    admin: 'Admin',
    backToShelf: 'Back to library',
    logout: 'Sign out',
    collapse: 'Collapse sidebar',
    expand: 'Expand sidebar',
    serviceDown: 'Service unreachable',
    noKey: 'API key not set',
    signedInAs: 'Signed in as {name}',
    breadcrumb: 'Breadcrumb',
  },
  money: {
    total: 'Total',
    spent: 'Spent',
    reserved: 'Reserved (running)',
    after: 'After this',
    budget: 'Budget',
    over: 'This exceeds your budget and will be rejected. Raise the budget in settings first.',
    changed: 'The amount is now {amount}. Please confirm again.',
    rateNote: 'Pricing basis: {note}. Your provider console bill is authoritative.',
    rateUnknown: 'not stated by the provider',
    confirm: '{action} ({amount})',
  },
}

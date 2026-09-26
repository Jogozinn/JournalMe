# Design System

JournalMe uses a quiet, dark-first visual language intended for long review
sessions.

- Canvas: near-black `#080a09`
- Raised surfaces: charcoal with subtle warm-green tint
- Positive financial state: restrained emerald
- Negative financial state: restrained coral
- Text: high-contrast warm white with muted sage secondary text
- Geometry: 14–22px card radii, soft one-pixel borders, very few pills
- Typography: Geist for interface text and Geist Mono for tabular numbers

Green and coral are reserved primarily for financial meaning. Focus rings use a
neutral mint. Touch targets are at least 44px, the mobile navigation includes
safe-area padding, and layouts must not introduce horizontal page scrolling.

Brand tokens and product copy live in `frontend/src/config/brand.ts`.


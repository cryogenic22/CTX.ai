# Twilio Video Business Rules

## Recording Rules
- Recording is only available for group and group-small room types
- Peer-to-peer rooms do not support server-side recording
- Recording rules can be set per-room or per-participant
- Rules use include/exclude lists with track type and publisher SID

## Composition Rules
- Compositions can only be created from completed rooms
- A room must have at least one recording to create a composition
- Composition resolution and format are configurable
- Trim time allows excluding portions at the start/end

## Participant Limits
- go rooms: max 2 participants
- peer-to-peer rooms: max 10 participants
- group-small rooms: max 4 participants
- group rooms: max 50 participants (configurable)

## Webhook Events
- room-created, room-ended
- participant-connected, participant-disconnected
- recording-started, recording-completed, recording-failed
- composition-completed, composition-failed

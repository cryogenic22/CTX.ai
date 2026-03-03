# Twilio Video Architecture

## Resource Hierarchy
- Room is the top-level container for video sessions
- Participants join Rooms and produce media tracks
- Recordings capture media from individual tracks or the entire room
- Compositions combine multiple recordings into a single media file
- Recording Rules control which tracks are recorded

## SID Pattern Convention
- All Twilio resources use SID (String Identifier) patterns
- Format: 2-letter prefix + 32 hexadecimal characters
- Prefixes are unique per resource type for quick identification

## Status Lifecycle
- Rooms: in-progress → completed (or failed)
- Participants: connected → disconnected
- Recordings: processing → completed (or failed/deleted)
- Compositions: enqueued → processing → completed (or failed/deleted)

## Media and Codecs
- Video codecs: VP8, H264
- Audio codecs: opus, PCMU
- Recording formats: mka (audio), mkv (video), mp4 (composition)
- Max participants varies by room type (peer-to-peer: 10, group: 50)

## Room Types
- go: basic rooms for small meetings
- peer-to-peer: direct P2P connections, no media server
- group: server-routed, supports recording and composition
- group-small: optimized group rooms for up to 4 participants

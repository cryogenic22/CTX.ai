# RESOURCE: RecordingRules

## Endpoints
- X-TWILIO /v1/Rooms/{RoomSid}/RecordingRules
- GET /v1/Rooms/{RoomSid}/RecordingRules
  Summary: Returns a list of Recording Rules for the Room.
  - Param: RoomSid (path, string)
- POST /v1/Rooms/{RoomSid}/RecordingRules
  Summary: Update the Recording Rules for the Room
  - Param: RoomSid (path, string)

## Relationships
- belongs_to: Rooms

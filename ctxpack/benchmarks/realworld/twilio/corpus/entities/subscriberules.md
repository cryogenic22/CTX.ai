# RESOURCE: SubscribeRules

## Endpoints
- X-TWILIO /v1/Rooms/{RoomSid}/Participants/{ParticipantSid}/SubscribeRules
- GET /v1/Rooms/{RoomSid}/Participants/{ParticipantSid}/SubscribeRules
  Summary: Returns a list of Subscribe Rules for the Participant.
  - Param: RoomSid (path, string)
  - Param: ParticipantSid (path, string)
- POST /v1/Rooms/{RoomSid}/Participants/{ParticipantSid}/SubscribeRules
  Summary: Update the Subscribe Rules for the Participant
  - Param: RoomSid (path, string)
  - Param: ParticipantSid (path, string)

## Relationships
- belongs_to: Rooms
- has_many: Participants

# RESOURCE: SubscribedTracks

## Endpoints
- X-TWILIO /v1/Rooms/{RoomSid}/Participants/{ParticipantSid}/SubscribedTracks/{Sid}
- GET /v1/Rooms/{RoomSid}/Participants/{ParticipantSid}/SubscribedTracks/{Sid}
  Summary: Returns a single Track resource represented by `track_sid`.  Note: This is one resource with the Video API that requires a SID, be Track Name on the subscriber side is not guaranteed to be unique.
  - Param: RoomSid (path, string)
  - Param: ParticipantSid (path, string)
  - Param: Sid (path, string)
- X-TWILIO /v1/Rooms/{RoomSid}/Participants/{ParticipantSid}/SubscribedTracks
- GET /v1/Rooms/{RoomSid}/Participants/{ParticipantSid}/SubscribedTracks
  Summary: Returns a list of tracks that are subscribed for the participant.
  - Param: RoomSid (path, string)
  - Param: ParticipantSid (path, string)
  - Param: PageSize (query, integer (int64))
  - Param: Page (query, integer)
  - Param: PageToken (query, string)

## Relationships
- belongs_to: Rooms
- has_many: Participants

# RESOURCE: PublishedTracks

## Endpoints
- X-TWILIO /v1/Rooms/{RoomSid}/Participants/{ParticipantSid}/PublishedTracks/{Sid}
- GET /v1/Rooms/{RoomSid}/Participants/{ParticipantSid}/PublishedTracks/{Sid}
  Summary: Returns a single Track resource represented by TrackName or SID.
  - Param: RoomSid (path, string)
  - Param: ParticipantSid (path, string)
  - Param: Sid (path, string)
- X-TWILIO /v1/Rooms/{RoomSid}/Participants/{ParticipantSid}/PublishedTracks
- GET /v1/Rooms/{RoomSid}/Participants/{ParticipantSid}/PublishedTracks
  Summary: Returns a list of tracks associated with a given Participant. Only `currently` Published Tracks are in the list resource.
  - Param: RoomSid (path, string)
  - Param: ParticipantSid (path, string)
  - Param: PageSize (query, integer (int64))
  - Param: Page (query, integer)
  - Param: PageToken (query, string)

## Relationships
- belongs_to: Rooms
- has_many: Participants

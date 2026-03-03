# RESOURCE: Participants

## Fields
- sid: string (nullable) — The unique string that we created to identify the RoomParticipant resource.
- room_sid: string (nullable) — The SID of the participant's room.
- account_sid: string (nullable) — The SID of the [Account](https://www.twilio.com/docs/iam/api/account) that created the RoomParticipant resource.
- status: room_participant_enum_status
- identity: string (nullable) — The application-defined string that uniquely identifies the resource's User within a Room. If a client joins with an existing Identity, the existing c...
- date_created: string (date-time) (nullable) — The date and time in GMT when the resource was created specified in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) format.
- date_updated: string (date-time) (nullable) — The date and time in GMT when the resource was last updated specified in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) format.
- start_time: string (date-time) (nullable) — The time of participant connected to the room in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601#UTC) format.
- end_time: string (date-time) (nullable) — The time when the participant disconnected from the room in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601#UTC) format.
- duration: integer (nullable) — The duration in seconds that the participant was `connected`. Populated only after the participant is `disconnected`.
- url: string (uri) (nullable) — The absolute URL of the resource.
- links: object (uri-map) (nullable) — The URLs of related resources.

## Endpoints
- X-TWILIO /v1/Rooms/{RoomSid}/Participants/{Sid}
- GET /v1/Rooms/{RoomSid}/Participants/{Sid}
  - Param: RoomSid (path, string)
  - Param: Sid (path, string)
- POST /v1/Rooms/{RoomSid}/Participants/{Sid}
  - Param: RoomSid (path, string)
  - Param: Sid (path, string)
- X-TWILIO /v1/Rooms/{RoomSid}/Participants
- GET /v1/Rooms/{RoomSid}/Participants
  - Param: RoomSid (path, string)
  - Param: Status (query, room_participant_enum_status)
  - Param: Identity (query, string)
  - Param: DateCreatedAfter (query, string (date-time))
  - Param: DateCreatedBefore (query, string (date-time))
  - Param: PageSize (query, integer (int64))
  - Param: Page (query, integer)
  - Param: PageToken (query, string)

## Relationships
- belongs_to: Rooms

# RESOURCE: Anonymize

## Fields
- sid: string (nullable) — The unique string that we created to identify the RoomParticipant resource.
- room_sid: string (nullable) — The SID of the participant's room.
- account_sid: string (nullable) — The SID of the [Account](https://www.twilio.com/docs/iam/api/account) that created the RoomParticipant resource.
- status: room_participant_anonymize_enum_status
- identity: string (nullable) — The SID of the participant.
- date_created: string (date-time) (nullable) — The date and time in GMT when the resource was created specified in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) format.
- date_updated: string (date-time) (nullable) — The date and time in GMT when the resource was last updated specified in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) format.
- start_time: string (date-time) (nullable) — The time of participant connected to the room in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601#UTC) format.
- end_time: string (date-time) (nullable) — The time when the participant disconnected from the room in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601#UTC) format.
- duration: integer (nullable) — The duration in seconds that the participant was `connected`. Populated only after the participant is `disconnected`.
- url: string (uri) (nullable) — The absolute URL of the resource.

## Endpoints
- X-TWILIO /v1/Rooms/{RoomSid}/Participants/{Sid}/Anonymize
- POST /v1/Rooms/{RoomSid}/Participants/{Sid}/Anonymize
  - Param: RoomSid (path, string)
  - Param: Sid (path, string)

## Relationships
- belongs_to: Rooms
- has_many: Participants

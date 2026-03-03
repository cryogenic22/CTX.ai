# RESOURCE: Transcriptions

## Fields
- ttid: string (nullable) — The unique string that we created to identify the transcriptions resource.
- account_sid: string (nullable) — The SID of the [Account](https://www.twilio.com/docs/iam/api/account) that created the Room resource.
- room_sid: string (nullable) — The SID of the transcriptions's room.
- source_sid: string (nullable) — The SID of the transcriptions's associated call.
- status: room_transcriptions_enum_status
- date_created: string (date-time) (nullable) — The date and time in GMT when the resource was created specified in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) format.
- date_updated: string (date-time) (nullable) — The date and time in GMT when the resource was last updated specified in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) format.
- start_time: string (date-time) (nullable) — The time of transcriptions connected to the room in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601#UTC) format.
- end_time: string (date-time) (nullable) — The time when the transcriptions disconnected from the room in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601#UTC) format.
- duration: integer (nullable) — The duration in seconds that the transcriptions were `connected`. Populated only after the transcriptions is `stopped`.
- url: string (uri) (nullable) — The absolute URL of the resource.
- configuration: object (nullable) — An JSON object that describes the video layout of the composition in terms of regions. See [Specifying Video Layouts](https://www.twilio.com/docs/vide...

## Endpoints
- X-TWILIO /v1/Rooms/{RoomSid}/Transcriptions/{Ttid}
- GET /v1/Rooms/{RoomSid}/Transcriptions/{Ttid}
  - Param: RoomSid (path, string)
  - Param: Ttid (path, string)
- POST /v1/Rooms/{RoomSid}/Transcriptions/{Ttid}
  - Param: RoomSid (path, string)
  - Param: Ttid (path, string)
- X-TWILIO /v1/Rooms/{RoomSid}/Transcriptions
- GET /v1/Rooms/{RoomSid}/Transcriptions
  - Param: RoomSid (path, string)
  - Param: PageSize (query, integer (int64))
  - Param: Page (query, integer)
  - Param: PageToken (query, string)
- POST /v1/Rooms/{RoomSid}/Transcriptions
  - Param: RoomSid (path, string)

## Relationships
- belongs_to: Rooms

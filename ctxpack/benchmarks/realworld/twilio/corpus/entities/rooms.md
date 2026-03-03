# RESOURCE: Rooms

## Fields
- sid: string (nullable) — The unique string that Twilio created to identify the Room resource.
- status: room_enum_room_status
- date_created: string (date-time) (nullable) — The date and time in GMT when the resource was created specified in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) format.
- date_updated: string (date-time) (nullable) — The date and time in GMT when the resource was last updated specified in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) format.
- account_sid: string (nullable) — The SID of the [Account](https://www.twilio.com/docs/iam/api/account) that created the Room resource.
- enable_turn: boolean (nullable) — Deprecated, now always considered to be true.
- unique_name: string (nullable) — An application-defined string that uniquely identifies the resource. It can be used as a `room_sid` in place of the resource's `sid` in the URL to add...
- status_callback: string (uri) (nullable) — The URL Twilio calls using the `status_callback_method` to send status information to your application on every room event. See [Status Callbacks](htt...
- status_callback_method: enum [GET, POST] (nullable) — The HTTP method Twilio uses to call `status_callback`. Can be `POST` or `GET` and defaults to `POST`.
- end_time: string (date-time) (nullable) — The UTC end time of the room in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601#UTC) format.
- duration: integer (nullable) — The duration of the room in seconds.
- type: room_enum_room_type
- max_participants: integer — The maximum number of concurrent Participants allowed in the room. 
- max_participant_duration: integer — The maximum number of seconds a Participant can be connected to the room. The maximum possible value is 86400 seconds (24 hours). The default is 14400...
- max_concurrent_published_tracks: integer (nullable) — The maximum number of published audio, video, and data tracks all participants combined are allowed to publish in the room at the same time. Check [Pr...
- record_participants_on_connect: boolean (nullable) — Whether to start recording when Participants connect.
- video_codecs: array (nullable) — An array of the video codecs that are supported when publishing a track in the room.  Can be: `VP8` and `H264`.
- media_region: string (nullable) — The region for the Room's media server.  Can be one of the [available Media Regions](https://www.twilio.com/docs/video/ip-addresses#media-servers).
- audio_only: boolean (nullable) — When set to true, indicates that the participants in the room will only publish audio. No video tracks will be allowed.
- empty_room_timeout: integer — Specifies how long (in minutes) a room will remain active after last participant leaves. Can be configured when creating a room via REST API. For Ad-H...
- unused_room_timeout: integer — Specifies how long (in minutes) a room will remain active if no one joins. Can be configured when creating a room via REST API. For Ad-Hoc rooms this ...
- large_room: boolean (nullable) — Indicates if this is a large room.
- url: string (uri) (nullable) — The absolute URL of the resource.
- links: object (uri-map) (nullable) — The URLs of related resources.

## Endpoints
- X-TWILIO /v1/Rooms/{Sid}
- GET /v1/Rooms/{Sid}
  - Param: Sid (path, string)
- POST /v1/Rooms/{Sid}
  - Param: Sid (path, string)
- X-TWILIO /v1/Rooms
- POST /v1/Rooms
- GET /v1/Rooms
  - Param: Status (query, room_enum_room_status)
  - Param: UniqueName (query, string)
  - Param: DateCreatedAfter (query, string (date-time))
  - Param: DateCreatedBefore (query, string (date-time))
  - Param: PageSize (query, integer (int64))
  - Param: Page (query, integer)
  - Param: PageToken (query, string)

# RESOURCE: Compositions

## Fields
- account_sid: string (nullable) — The SID of the [Account](https://www.twilio.com/docs/iam/api/account) that created the Composition resource.
- status: composition_enum_status
- date_created: string (date-time) (nullable) — The date and time in GMT when the resource was created specified in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) format.
- date_completed: string (date-time) (nullable) — The date and time in GMT when the composition's media processing task finished, specified in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) format...
- date_deleted: string (date-time) (nullable) — The date and time in GMT when the composition generated media was deleted, specified in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) format.
- sid: string (nullable) — The unique string that we created to identify the Composition resource.
- room_sid: string (nullable) — The SID of the Group Room that generated the audio and video tracks used in the composition. All media sources included in a composition must belong t...
- audio_sources: array (nullable) — The array of track names to include in the composition. The composition includes all audio sources specified in `audio_sources` except those specified...
- audio_sources_excluded: array (nullable) — The array of track names to exclude from the composition. The composition includes all audio sources specified in `audio_sources` except for those spe...
- video_layout: any (nullable) — An object that describes the video layout of the composition in terms of regions. See [Specifying Video Layouts](https://www.twilio.com/docs/video/api...
- resolution: string (nullable) — The dimensions of the video image in pixels expressed as columns (width) and rows (height). The string's format is `{width}x{height}`, such as `640x48...
- trim: boolean (nullable) — Whether to remove intervals with no media, as specified in the POST request that created the composition. Compositions with `trim` enabled are shorter...
- format: composition_enum_format
- bitrate: integer — The average bit rate of the composition's media.
- size: integer (int64) (nullable) — The size of the composed media file in bytes.
- duration: integer — The duration of the composition's media file in seconds.
- media_external_location: string (uri) (nullable) — The URL of the media file associated with the composition when stored externally. See [External S3 Compositions](/docs/video/api/external-s3-compositi...
- status_callback: string (uri) (nullable) — The URL called using the `status_callback_method` to send status information on every composition event.
- status_callback_method: enum [GET, POST] (nullable) — The HTTP method used to call `status_callback`. Can be: `POST` or `GET`, defaults to `POST`.
- url: string (uri) (nullable) — The absolute URL of the resource.
- links: object (uri-map) (nullable) — The URL of the media file associated with the composition.

## Endpoints
- X-TWILIO /v1/Compositions/{Sid}
- GET /v1/Compositions/{Sid}
  Summary: Returns a single Composition resource identified by a Composition SID.
  - Param: Sid (path, string)
- DELETE /v1/Compositions/{Sid}
  Summary: Delete a Recording Composition resource identified by a Composition SID.
  - Param: Sid (path, string)
- X-TWILIO /v1/Compositions
- GET /v1/Compositions
  Summary: List of all Recording compositions.
  - Param: Status (query, composition_enum_status)
  - Param: DateCreatedAfter (query, string (date-time))
  - Param: DateCreatedBefore (query, string (date-time))
  - Param: RoomSid (query, string)
  - Param: PageSize (query, integer (int64))
  - Param: Page (query, integer)
  - Param: PageToken (query, string)
- POST /v1/Compositions

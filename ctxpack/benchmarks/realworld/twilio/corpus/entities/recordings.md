# RESOURCE: Recordings

## Fields
- account_sid: string (nullable) — The SID of the [Account](https://www.twilio.com/docs/iam/api/account) that created the Recording resource.
- status: recording_enum_status
- date_created: string (date-time) (nullable) — The date and time in GMT when the resource was created specified in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) format.
- sid: string (nullable) — The unique string that we created to identify the Recording resource.
- source_sid: string (nullable) — The SID of the recording source. For a Room Recording, this value is a `track_sid`.
- size: integer (int64) (nullable) — The size of the recorded track, in bytes.
- url: string (uri) (nullable) — The absolute URL of the resource.
- type: recording_enum_type
- duration: integer (nullable) — The duration of the recording in seconds rounded to the nearest second. Sub-second tracks have a `Duration` property of 1 second
- container_format: recording_enum_format
- codec: recording_enum_codec
- grouping_sids: any (nullable) — A list of SIDs related to the recording. Includes the `room_sid` and `participant_sid`.
- track_name: string (nullable) — The name that was given to the source track of the recording. If no name is given, the `source_sid` is used.
- offset: integer (int64) (nullable) — The time in milliseconds elapsed between an arbitrary point in time, common to all group rooms, and the moment when the source room of this track star...
- media_external_location: string (uri) (nullable) — The URL of the media file associated with the recording when stored externally. See [External S3 Recordings](/docs/video/api/external-s3-recordings) f...
- status_callback: string (uri) (nullable) — The URL called using the `status_callback_method` to send status information on every recording event.
- status_callback_method: enum [GET, POST] (nullable) — The HTTP method used to call `status_callback`. Can be: `POST` or `GET`, defaults to `POST`.
- links: object (uri-map) (nullable) — The URLs of related resources.

## Endpoints
- X-TWILIO /v1/Recordings/{Sid}
- GET /v1/Recordings/{Sid}
  Summary: Returns a single Recording resource identified by a Recording SID.
  - Param: Sid (path, string)
- DELETE /v1/Recordings/{Sid}
  Summary: Delete a Recording resource identified by a Recording SID.
  - Param: Sid (path, string)
- X-TWILIO /v1/Recordings
- GET /v1/Recordings
  Summary: List of all Track recordings.
  - Param: Status (query, recording_enum_status)
  - Param: SourceSid (query, string)
  - Param: GroupingSid (query, array)
  - Param: DateCreatedAfter (query, string (date-time))
  - Param: DateCreatedBefore (query, string (date-time))
  - Param: MediaType (query, recording_enum_type)
  - Param: PageSize (query, integer (int64))
  - Param: Page (query, integer)
  - Param: PageToken (query, string)
- X-TWILIO /v1/Rooms/{RoomSid}/Recordings/{Sid}
- GET /v1/Rooms/{RoomSid}/Recordings/{Sid}
  - Param: RoomSid (path, string)
  - Param: Sid (path, string)
- DELETE /v1/Rooms/{RoomSid}/Recordings/{Sid}
  - Param: RoomSid (path, string)
  - Param: Sid (path, string)
- X-TWILIO /v1/Rooms/{RoomSid}/Recordings
- GET /v1/Rooms/{RoomSid}/Recordings
  - Param: RoomSid (path, string)
  - Param: Status (query, room_recording_enum_status)
  - Param: SourceSid (query, string)
  - Param: DateCreatedAfter (query, string (date-time))
  - Param: DateCreatedBefore (query, string (date-time))
  - Param: PageSize (query, integer (int64))
  - Param: Page (query, integer)
  - Param: PageToken (query, string)

## Relationships
- belongs_to: Rooms

# RESOURCE: CompositionHooks

## Endpoints
- X-TWILIO /v1/CompositionHooks/{Sid}
- GET /v1/CompositionHooks/{Sid}
  Summary: Returns a single CompositionHook resource identified by a CompositionHook SID.
  - Param: Sid (path, string)
- DELETE /v1/CompositionHooks/{Sid}
  Summary: Delete a Recording CompositionHook resource identified by a `CompositionHook SID`.
  - Param: Sid (path, string)
- POST /v1/CompositionHooks/{Sid}
  - Param: Sid (path, string)
- X-TWILIO /v1/CompositionHooks
- GET /v1/CompositionHooks
  Summary: List of all Recording CompositionHook resources.
  - Param: Enabled (query, boolean)
  - Param: DateCreatedAfter (query, string (date-time))
  - Param: DateCreatedBefore (query, string (date-time))
  - Param: FriendlyName (query, string)
  - Param: PageSize (query, integer (int64))
  - Param: Page (query, integer)
  - Param: PageToken (query, string)
- POST /v1/CompositionHooks

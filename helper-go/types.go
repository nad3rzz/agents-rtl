package main

import "encoding/json"

type debuggerTarget struct {
	ID                   string `json:"id"`
	ParentID             string `json:"parentId"`
	Type                 string `json:"type"`
	URL                  string `json:"url"`
	Title                string `json:"title"`
	WebSocketDebuggerURL string `json:"webSocketDebuggerUrl"`
}

type runtimeContext struct {
	ID      int `json:"id"`
	AuxData struct {
		IsDefault bool `json:"isDefault"`
	} `json:"auxData"`
}

type codexConversation struct {
	ID    string `json:"id"`
	Title string `json:"title"`
	Path  string `json:"path"`
}

type codexArchiveRequest struct {
	ID          string  `json:"id"`
	Title       string  `json:"title"`
	RequestedAt float64 `json:"requestedAt"`
}

type codexTabOrderRequest struct {
	IDs         []string `json:"ids"`
	RequestedAt float64  `json:"requestedAt"`
}

type codexActivityKeyRequest struct {
	ID          string  `json:"id"`
	ActivityKey string  `json:"activityKey"`
	RequestedAt float64 `json:"requestedAt"`
}

type codexPreferencePayload struct {
	TabOrderRequests    []codexTabOrderRequest    `json:"tabOrderRequests"`
	ActivityKeyRequests []codexActivityKeyRequest `json:"activityKeyRequests"`
}

type codexSharedPreferences struct {
	CodexChatOrder        []string          `json:"codexChatOrder,omitempty"`
	CodexChatActivityKeys map[string]string `json:"codexChatActivityKeys,omitempty"`
}

type codexArchiveRow struct {
	Archived int
	CWD      string
}

type sessionIndexRow struct {
	ID         string `json:"id"`
	ThreadName string `json:"thread_name"`
}

type devtoolsResponse struct {
	ID     int             `json:"id"`
	Result json.RawMessage `json:"result"`
	Error  json.RawMessage `json:"error"`
	Method string          `json:"method"`
	Params json.RawMessage `json:"params"`
}

type evaluateResult struct {
	Result struct {
		Value any `json:"value"`
	} `json:"result"`
	ExceptionDetails any `json:"exceptionDetails"`
}

type contextCreatedParams struct {
	Context runtimeContext `json:"context"`
}

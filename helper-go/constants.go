package main

import "time"

const (
	chatgptWebviewURLMarker                  = "extensionId=openai.chatgpt"
	geminiWebviewURLMarker                   = "extensionId=google.geminicodeassist"
	workbenchURLMarker                       = "/workbench/workbench.html"
	websocketGUID                            = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
	commandTimeout                           = 3 * time.Second
	codexArchiveHelpTimeout                  = 3 * time.Second
	codexArchiveCommandTimeout               = 15 * time.Second
	codexIpcTimeout                          = 5 * time.Second
	codexIpcFrameHeaderBytes                 = 4
	codexIpcMaxFrameBytes                    = 256 * 1024 * 1024
	codexIpcInitializeVersion                = 0
	codexIpcArchivedVersion                  = 2
	codexIpcClientType                       = "agents-rtl"
	codexIpcHostID                           = "local"
	maxCodexChatTabs                         = 24
	codexArchiveRequestsKey                  = "agentsRtl.codexChatTabs.archiveRequests"
	codexProcessedArchivesKey                = "agentsRtl.codexChatTabs.processedArchiveIds"
	codexTabOrderRequestsKey                 = "agentsRtl.codexChatTabs.orderRequests"
	codexActivityRequestsKey                 = "agentsRtl.codexChatTabs.activityKeyRequests"
	codexLatestAgentReplyActivityRequestsKey = "agentsRtl.codexChatTabs.latestAgentReplyActivityRequests"
	codexPreferencesFileName                 = "agents-rtl-preferences.json"
)

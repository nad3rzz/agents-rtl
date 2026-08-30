package main

import (
	"bufio"
	"bytes"
	"crypto/rand"
	"crypto/sha1"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const contextProbeScript = `
(() => {
  const bodyText = document.body?.innerText || "";
  const nativeChatPanel = document.getElementById("workbench.panel.chat");
  return {
    title: document.title,
    bodyTextLength: bodyText.length,
    hasMessages: Boolean(document.querySelector("[data-content-search-unit-key]")),
    hasThreadRoot: Boolean(
      document.querySelector('[class*="react-scroll-to-bottom"]') ||
      document.querySelector(".thread-scroll-container")
    ),
    hasNativeChatPanel: Boolean(nativeChatPanel),
    hasNativeChatMessages: Boolean(
      nativeChatPanel?.querySelector(".chat-markdown-part.rendered-markdown,.interactive-item-container,.monaco-list[aria-label='Chat']")
    ),
    hasAntigravityNativeAgent: Boolean(
      document.getElementById("conversation") ||
      document.getElementById("antigravity.agentSidePanelInputBox") ||
      document.querySelector(".antigravity-agent-side-panel")
    ),
    hasGeminiCodeAssist: Boolean(
      document.body?.classList?.contains("gm3") &&
      document.querySelector("app-ai-chat,chat-history,chat-input,.chat-submit-input[contenteditable]")
    ),
    hasRtl: Boolean(window.__agentsRtl?.installed),
  };
})();
`

type devtoolsClient struct {
	conn     net.Conn
	reader   *bufio.Reader
	mu       sync.Mutex
	pending  map[int]chan devtoolsResponse
	contexts []runtimeContext
	nextID   atomic.Int64
}

func evaluateInReadyTargetContexts(port int, target debuggerTarget, expression string) ([]any, error) {
	parsedURL, err := url.Parse(target.WebSocketDebuggerURL)
	if err != nil {
		return nil, err
	}

	client, err := connectDevtools(port, parsedURL.RequestURI())
	if err != nil {
		return nil, err
	}
	defer client.close()

	if _, err := client.command("Runtime.enable", map[string]any{}); err != nil {
		return nil, err
	}

	time.Sleep(250 * time.Millisecond)

	contextIDs, err := client.readyContextIDs()
	if err != nil {
		return nil, err
	}

	values := make([]any, 0, len(contextIDs))
	for _, contextID := range contextIDs {
		value, err := client.evaluate(contextID, expression)
		if err != nil {
			return nil, fmt.Errorf("context %d evaluation failed: %w", contextID, err)
		}
		values = append(values, value)
	}

	return values, nil
}

func connectDevtools(port int, websocketPath string) (*devtoolsClient, error) {
	conn, err := net.DialTimeout("tcp", fmt.Sprintf("127.0.0.1:%d", port), 3*time.Second)
	if err != nil {
		return nil, err
	}

	keyBytes := make([]byte, 16)
	if _, err := rand.Read(keyBytes); err != nil {
		conn.Close()
		return nil, err
	}

	key := base64.StdEncoding.EncodeToString(keyBytes)
	request := strings.Join([]string{
		fmt.Sprintf("GET %s HTTP/1.1", websocketPath),
		fmt.Sprintf("Host: 127.0.0.1:%d", port),
		"Upgrade: websocket",
		"Connection: Upgrade",
		fmt.Sprintf("Sec-WebSocket-Key: %s", key),
		"Sec-WebSocket-Version: 13",
		"",
		"",
	}, "\r\n")

	if _, err := conn.Write([]byte(request)); err != nil {
		conn.Close()
		return nil, err
	}

	reader := bufio.NewReader(conn)
	statusLine, err := reader.ReadString('\n')
	if err != nil {
		conn.Close()
		return nil, err
	}

	if !strings.Contains(statusLine, "101") {
		conn.Close()
		return nil, fmt.Errorf("websocket handshake failed: %s", strings.TrimSpace(statusLine))
	}

	expectedAccept := expectedWebsocketAccept(key)
	acceptFound := false
	for {
		line, err := reader.ReadString('\n')
		if err != nil {
			conn.Close()
			return nil, err
		}

		line = strings.TrimSpace(line)
		if line == "" {
			break
		}

		if strings.HasPrefix(strings.ToLower(line), "sec-websocket-accept:") &&
			strings.Contains(line, expectedAccept) {
			acceptFound = true
		}
	}

	if !acceptFound {
		conn.Close()
		return nil, errors.New("websocket accept header mismatch")
	}

	client := &devtoolsClient{
		conn:    conn,
		reader:  reader,
		pending: make(map[int]chan devtoolsResponse),
	}

	go client.readLoop()
	return client, nil
}

func expectedWebsocketAccept(key string) string {
	hash := sha1.Sum([]byte(key + websocketGUID))
	return base64.StdEncoding.EncodeToString(hash[:])
}

func (client *devtoolsClient) readyContextIDs() ([]int, error) {
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		client.mu.Lock()
		contexts := append([]runtimeContext(nil), client.contexts...)
		client.mu.Unlock()

		readyContextIDs := []int{}
		seenContextIDs := make(map[int]bool)
		for _, context := range contexts {
			if !context.AuxData.IsDefault {
				continue
			}

			value, err := client.evaluate(context.ID, contextProbeScript)
			if err != nil {
				continue
			}

			if isReadyProbe(value) && !seenContextIDs[context.ID] {
				readyContextIDs = append(readyContextIDs, context.ID)
				seenContextIDs[context.ID] = true
			}
		}

		if len(readyContextIDs) > 0 {
			return readyContextIDs, nil
		}

		time.Sleep(150 * time.Millisecond)
	}

	return nil, errors.New("ready agent context not found")
}

func isReadyProbe(value any) bool {
	payload, ok := value.(map[string]any)
	if !ok {
		return false
	}

	if payload["hasMessages"] == true ||
		payload["hasThreadRoot"] == true ||
		payload["hasNativeChatPanel"] == true ||
		payload["hasNativeChatMessages"] == true ||
		payload["hasAntigravityNativeAgent"] == true ||
		payload["hasGeminiCodeAssist"] == true {
		return true
	}

	bodyTextLength, ok := payload["bodyTextLength"].(float64)
	return ok && bodyTextLength > 100
}

func (client *devtoolsClient) evaluate(contextID int, expression string) (any, error) {
	result, err := client.command("Runtime.evaluate", map[string]any{
		"expression":    expression,
		"contextId":     contextID,
		"returnByValue": true,
		"awaitPromise":  true,
	})
	if err != nil {
		return nil, err
	}

	var payload evaluateResult
	if err := json.Unmarshal(result, &payload); err != nil {
		return nil, err
	}

	if payload.ExceptionDetails != nil {
		return nil, fmt.Errorf("runtime exception: %v", payload.ExceptionDetails)
	}

	return payload.Result.Value, nil
}

func (client *devtoolsClient) command(method string, params map[string]any) (json.RawMessage, error) {
	commandID := int(client.nextID.Add(1))
	responseChannel := make(chan devtoolsResponse, 1)

	client.mu.Lock()
	client.pending[commandID] = responseChannel
	client.mu.Unlock()

	requestPayload, err := json.Marshal(map[string]any{
		"id":     commandID,
		"method": method,
		"params": params,
	})
	if err != nil {
		return nil, err
	}

	if err := client.writeTextFrame(requestPayload); err != nil {
		return nil, err
	}

	select {
	case response := <-responseChannel:
		if len(response.Error) > 0 {
			return nil, fmt.Errorf("devtools error: %s", string(response.Error))
		}
		return response.Result, nil
	case <-time.After(commandTimeout):
		client.mu.Lock()
		delete(client.pending, commandID)
		client.mu.Unlock()
		return nil, fmt.Errorf("devtools command timed out: %s", method)
	}
}

func (client *devtoolsClient) readLoop() {
	for {
		opcode, payload, err := client.readFrame()
		if err != nil {
			client.rejectAll(err)
			return
		}

		if opcode == 0x8 {
			client.rejectAll(errors.New("websocket closed"))
			return
		}

		if opcode != 0x1 {
			continue
		}

		var response devtoolsResponse
		if err := json.Unmarshal(payload, &response); err != nil {
			continue
		}

		if response.Method == "Runtime.executionContextCreated" {
			var params contextCreatedParams
			if err := json.Unmarshal(response.Params, &params); err == nil {
				client.mu.Lock()
				client.contexts = append(client.contexts, params.Context)
				client.mu.Unlock()
			}
			continue
		}

		if response.ID == 0 {
			continue
		}

		client.mu.Lock()
		responseChannel := client.pending[response.ID]
		delete(client.pending, response.ID)
		client.mu.Unlock()

		if responseChannel != nil {
			responseChannel <- response
		}
	}
}

func (client *devtoolsClient) rejectAll(err error) {
	client.mu.Lock()
	defer client.mu.Unlock()

	for commandID, responseChannel := range client.pending {
		delete(client.pending, commandID)
		close(responseChannel)
	}

	_ = err
}

func (client *devtoolsClient) readFrame() (byte, []byte, error) {
	header := make([]byte, 2)
	if _, err := io.ReadFull(client.reader, header); err != nil {
		return 0, nil, err
	}

	opcode := header[0] & 0x0f
	masked := header[1]&0x80 != 0
	payloadLength := uint64(header[1] & 0x7f)

	switch payloadLength {
	case 126:
		extended := make([]byte, 2)
		if _, err := io.ReadFull(client.reader, extended); err != nil {
			return 0, nil, err
		}
		payloadLength = uint64(binary.BigEndian.Uint16(extended))
	case 127:
		extended := make([]byte, 8)
		if _, err := io.ReadFull(client.reader, extended); err != nil {
			return 0, nil, err
		}
		payloadLength = binary.BigEndian.Uint64(extended)
		if payloadLength > math.MaxInt32 {
			return 0, nil, errors.New("websocket frame too large")
		}
	}

	var mask []byte
	if masked {
		mask = make([]byte, 4)
		if _, err := io.ReadFull(client.reader, mask); err != nil {
			return 0, nil, err
		}
	}

	payload := make([]byte, payloadLength)
	if _, err := io.ReadFull(client.reader, payload); err != nil {
		return 0, nil, err
	}

	if masked {
		for index := range payload {
			payload[index] ^= mask[index%4]
		}
	}

	return opcode, payload, nil
}

func (client *devtoolsClient) writeTextFrame(payload []byte) error {
	var frame bytes.Buffer
	frame.WriteByte(0x81)

	payloadLength := len(payload)
	switch {
	case payloadLength < 126:
		frame.WriteByte(byte(0x80 | payloadLength))
	case payloadLength <= 0xffff:
		frame.WriteByte(0x80 | 126)
		extended := make([]byte, 2)
		binary.BigEndian.PutUint16(extended, uint16(payloadLength))
		frame.Write(extended)
	default:
		frame.WriteByte(0x80 | 127)
		extended := make([]byte, 8)
		binary.BigEndian.PutUint64(extended, uint64(payloadLength))
		frame.Write(extended)
	}

	mask := make([]byte, 4)
	if _, err := rand.Read(mask); err != nil {
		return err
	}
	frame.Write(mask)

	maskedPayload := make([]byte, payloadLength)
	for index := range payload {
		maskedPayload[index] = payload[index] ^ mask[index%4]
	}
	frame.Write(maskedPayload)

	_, err := client.conn.Write(frame.Bytes())
	return err
}

func (client *devtoolsClient) close() {
	_ = client.conn.Close()
}

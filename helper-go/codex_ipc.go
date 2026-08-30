package main

import (
	"crypto/rand"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/user"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

func broadcastCodexThreadArchived(conversationID string, cwd string) error {
	socketPath, err := codexIpcSocketPath()
	if err != nil {
		return err
	}

	conn, err := net.DialTimeout("unix", socketPath, codexIpcTimeout)
	if err != nil {
		return fmt.Errorf("cannot connect to Codex IPC socket %q: %w", socketPath, err)
	}
	defer conn.Close()
	if err := conn.SetDeadline(time.Now().Add(codexIpcTimeout)); err != nil {
		return err
	}

	requestID, err := newCodexIpcRequestID()
	if err != nil {
		return err
	}
	initializeMessage := map[string]any{
		"type":           "request",
		"requestId":      requestID,
		"sourceClientId": "initializing-client",
		"version":        codexIpcInitializeVersion,
		"method":         "initialize",
		"params": map[string]any{
			"clientType": codexIpcClientType,
		},
	}
	if err := writeCodexIpcMessage(conn, initializeMessage); err != nil {
		return err
	}
	initializeResponse, err := readCodexIpcMessage(conn)
	if err != nil {
		return err
	}
	clientID, err := codexIpcClientIDFromInitializeResponse(initializeResponse)
	if err != nil {
		return err
	}

	archiveMessage := map[string]any{
		"type":           "broadcast",
		"method":         "thread-archived",
		"sourceClientId": clientID,
		"version":        codexIpcArchivedVersion,
		"params": map[string]any{
			"hostId":         codexIpcHostID,
			"conversationId": conversationID,
			"cwd":            cwd,
		},
	}
	return writeCodexIpcMessage(conn, archiveMessage)
}

func codexIpcSocketPath() (string, error) {
	if runtime.GOOS == "windows" {
		return "", errors.New("Codex IPC broadcast is not supported on Windows")
	}
	currentUser, err := user.Current()
	if err != nil {
		return "", err
	}
	userID := strings.TrimSpace(currentUser.Uid)
	if userID == "" {
		return "", errors.New("current user id is empty")
	}

	socketName := "ipc.sock"
	if userID != "0" {
		socketName = "ipc-" + userID + ".sock"
	}
	return filepath.Join(os.TempDir(), "codex-ipc", socketName), nil
}

func newCodexIpcRequestID() (string, error) {
	requestIDBytes := make([]byte, 16)
	if _, err := rand.Read(requestIDBytes); err != nil {
		return "", err
	}
	requestIDBytes[6] = (requestIDBytes[6] & 0x0f) | 0x40
	requestIDBytes[8] = (requestIDBytes[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", requestIDBytes[0:4], requestIDBytes[4:6], requestIDBytes[6:8], requestIDBytes[8:10], requestIDBytes[10:16]), nil
}

func writeCodexIpcMessage(conn net.Conn, message map[string]any) error {
	payload, err := json.Marshal(message)
	if err != nil {
		return err
	}
	if len(payload) > codexIpcMaxFrameBytes {
		return fmt.Errorf("Codex IPC message exceeds %d bytes", codexIpcMaxFrameBytes)
	}

	header := make([]byte, codexIpcFrameHeaderBytes)
	binary.LittleEndian.PutUint32(header, uint32(len(payload)))
	if _, err := conn.Write(append(header, payload...)); err != nil {
		return err
	}
	return nil
}

func readCodexIpcMessage(conn net.Conn) (map[string]any, error) {
	header := make([]byte, codexIpcFrameHeaderBytes)
	if _, err := io.ReadFull(conn, header); err != nil {
		return nil, err
	}
	payloadSize := binary.LittleEndian.Uint32(header)
	if payloadSize > codexIpcMaxFrameBytes {
		return nil, fmt.Errorf("Codex IPC frame exceeds %d bytes", codexIpcMaxFrameBytes)
	}
	payload := make([]byte, int(payloadSize))
	if _, err := io.ReadFull(conn, payload); err != nil {
		return nil, err
	}

	message := map[string]any{}
	if err := json.Unmarshal(payload, &message); err != nil {
		return nil, err
	}
	return message, nil
}

func codexIpcClientIDFromInitializeResponse(message map[string]any) (string, error) {
	if stringMapValue(message, "type") != "response" {
		return "", fmt.Errorf("unexpected Codex IPC initialize response type: %q", stringMapValue(message, "type"))
	}
	if stringMapValue(message, "resultType") != "success" {
		return "", fmt.Errorf("Codex IPC initialize failed: %s", stringMapValue(message, "error"))
	}

	result, ok := message["result"].(map[string]any)
	if !ok {
		return "", errors.New("Codex IPC initialize response result is missing")
	}
	clientID := stringMapValue(result, "clientId")
	if clientID == "" {
		return "", errors.New("Codex IPC initialize response clientId is missing")
	}
	return clientID, nil
}

func stringMapValue(values map[string]any, key string) string {
	value, ok := values[key].(string)
	if !ok {
		return ""
	}
	return strings.TrimSpace(value)
}

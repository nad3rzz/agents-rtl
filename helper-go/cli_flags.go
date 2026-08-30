package main

import (
	"errors"
	"fmt"
	"strconv"
	"strings"
)

type portFlags []int

func (ports *portFlags) String() string {
	values := make([]string, 0, len(*ports))
	for _, port := range *ports {
		values = append(values, fmt.Sprint(port))
	}
	return strings.Join(values, ",")
}

func (ports *portFlags) Set(value string) error {
	port, err := parseDevtoolsPort(value)
	if err != nil {
		return err
	}

	*ports = append(*ports, port)
	return nil
}

func validateRequiredDevtoolsPorts(ports portFlags) error {
	if len(ports) == 0 {
		return errors.New("at least one --port is required")
	}
	return nil
}

func validateResourceMonitorArguments(ports portFlags, resourceMonitorPort int, extensionHostProcessID int) error {
	if resourceMonitorPort == 0 && extensionHostProcessID == 0 {
		return nil
	}
	if resourceMonitorPort == 0 || extensionHostProcessID == 0 {
		return errors.New("--resource-monitor-port and --extension-host-pid must be provided together")
	}
	if extensionHostProcessID < 1 {
		return fmt.Errorf("extension host process ID must be positive: %d", extensionHostProcessID)
	}
	for _, port := range ports {
		if port == resourceMonitorPort {
			return nil
		}
	}
	return fmt.Errorf("resource monitor port %d is not present in --port values", resourceMonitorPort)
}

type stringFlags []string

func (values *stringFlags) String() string {
	return strings.Join(*values, ",")
}

func (values *stringFlags) Set(value string) error {
	trimmedValue := strings.TrimSpace(value)
	if trimmedValue == "" {
		return errors.New("workspace-cwd cannot be empty")
	}

	*values = append(*values, trimmedValue)
	return nil
}

func parseDevtoolsPort(value string) (int, error) {
	port, err := strconv.Atoi(value)
	if err != nil {
		return 0, fmt.Errorf("invalid port %q: %w", value, err)
	}
	if port < 1 || port > 65535 {
		return 0, fmt.Errorf("port out of range: %d", port)
	}
	return port, nil
}

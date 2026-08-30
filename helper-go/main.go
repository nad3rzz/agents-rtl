package main

import (
	"flag"
	"log"
	"os"
	"time"
)

func main() {
	ports := portFlags{}
	workspaceCWDs := stringFlags{}
	flag.Var(&ports, "port", "DevTools port. May be provided more than once")
	flag.Var(&workspaceCWDs, "workspace-cwd", "Workspace cwd used to scope Codex chat tabs. May be provided more than once")
	intervalMs := flag.Int("interval-ms", 2500, "watch interval in milliseconds")
	codexCliPath := flag.String("codex-cli", "", "Codex CLI path used for archiving Codex chats")
	resourceMonitorPort := flag.Int("resource-monitor-port", 0, "Primary DevTools port whose Codex process may be monitored")
	extensionHostProcessID := flag.Int("extension-host-pid", 0, "Extension Host process ID used to isolate the current Codex backend")
	flag.Parse()

	if *intervalMs < 500 {
		log.Fatal("interval-ms must be >= 500")
	}
	if err := validateRequiredDevtoolsPorts(ports); err != nil {
		log.Fatal(err)
	}
	if err := validateResourceMonitorArguments(ports, *resourceMonitorPort, *extensionHostProcessID); err != nil {
		log.Fatal(err)
	}

	var resourceMonitor *codexResourceMonitor
	if *resourceMonitorPort != 0 {
		resourceMonitor = newCodexResourceMonitor(*extensionHostProcessID)
	}

	ticker := time.NewTicker(time.Duration(*intervalMs) * time.Millisecond)
	defer ticker.Stop()

	for {
		for _, port := range ports {
			var monitorForPort *codexResourceMonitor
			if port == *resourceMonitorPort {
				monitorForPort = resourceMonitor
			}
			if err := injectAll(port, []string(workspaceCWDs), *codexCliPath, monitorForPort); err != nil {
				log.Printf("inject failed on port %d: %v", port, err)
			}
		}
		<-ticker.C
	}
}

func init() {
	log.SetOutput(os.Stdout)
	log.SetFlags(log.LstdFlags)
}

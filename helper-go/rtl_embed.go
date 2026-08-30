package main

import (
	"embed"
	"path"
	"sort"
	"strings"
)

//go:embed rtl_script_parts/*.js
var rtlScriptParts embed.FS

var rtlScript = mustAssembleRTLScript()

func mustAssembleRTLScript() string {
	entries, err := rtlScriptParts.ReadDir("rtl_script_parts")
	if err != nil {
		panic("read RTL script parts: " + err.Error())
	}
	if len(entries) == 0 {
		panic("RTL script parts are missing")
	}

	partNames := make([]string, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() {
			panic("RTL script parts directory contains nested directory: " + entry.Name())
		}
		partName := entry.Name()
		if !strings.HasSuffix(partName, ".js") {
			panic("RTL script parts directory contains non-JS file: " + partName)
		}
		partNames = append(partNames, partName)
	}
	sort.Strings(partNames)

	var builder strings.Builder
	for _, partName := range partNames {
		partContent, err := rtlScriptParts.ReadFile(path.Join("rtl_script_parts", partName))
		if err != nil {
			panic("read RTL script part " + partName + ": " + err.Error())
		}
		builder.Write(partContent)
	}
	return builder.String()
}

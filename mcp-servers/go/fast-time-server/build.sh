#!/bin/bash
go mod tidy
go build -trimpath -ldflags "-s -w" -o fast-time-server

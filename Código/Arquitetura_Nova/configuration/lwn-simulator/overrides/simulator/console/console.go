package console

import (
	"log"
	"sync"
	"time"

	socketio "github.com/googollee/go-socket.io"
)

type socketEvent struct {
	eventName string
	data      []interface{}
}

var (
	wsMu        sync.RWMutex
	activeWS    socketio.Conn
	emitChan    = make(chan socketEvent, 256)
	workerStart sync.Once
)

func startEmitWorker() {
	workerStart.Do(func() {
		go func() {
			for ev := range emitChan {
				wsMu.RLock()
				conn := activeWS
				wsMu.RUnlock()
				if conn == nil {
					continue
				}

				done := make(chan struct{})
				go func(c socketio.Conn, e socketEvent) {
					defer func() {
						_ = recover()
						close(done)
					}()
					c.Emit(e.eventName, e.data...)
				}(conn, ev)

				select {
				case <-done:
				case <-time.After(500 * time.Millisecond):
					// Se o WebSocket travar (aba fechada/desconectada), limpa a referência
					// para nunca bloquear o envio de pacotes LoRaWAN do simulador.
					wsMu.Lock()
					if activeWS == conn {
						activeWS = nil
					}
					wsMu.Unlock()
				}
			}
		}()
	})
}

// Console represents a socket connection to send messages to the web terminal
type Console struct {
	WebSocket socketio.Conn
}

// PrintLog prints a message to the command line stdout
func (c *Console) PrintLog(message string) {
	log.Println(message)
}

// PrintSocket prints a message to the web terminal via a non-blocking queue
func (c *Console) PrintSocket(eventName string, data ...interface{}) {
	startEmitWorker()
	select {
	case emitChan <- socketEvent{eventName: eventName, data: data}:
	default:
		// Se a fila estiver cheia, descarta o evento visual sem travar a simulação
	}
}

// SetupWebSocket sets the socket connection for the Console
func (c *Console) SetupWebSocket(WebSocket *socketio.Conn) {
	startEmitWorker()
	wsMu.Lock()
	if WebSocket != nil {
		activeWS = *WebSocket
		c.WebSocket = *WebSocket
	} else {
		activeWS = nil
		c.WebSocket = nil
	}
	wsMu.Unlock()
}


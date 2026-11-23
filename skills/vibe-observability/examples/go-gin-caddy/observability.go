// Package observability provides a production-ready Go + Gin starter:
// - Stdlib log/slog JSON logging (ready for Docker stdout -> Pigsty Loki)
// - X-Request-Id correlation across logs, responses, and Sentry tags
// - sentry-go + sentrygin panic/error capture with bounded sampling & PII off
// - Separate /healthz (liveness) and /readyz (DB/Valkey readiness) endpoints
package observability

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"log/slog"
	"net/http"
	"os"
	"time"

	"github.com/getsentry/sentry-go"
	sentrygin "github.com/getsentry/sentry-go/gin"
	"github.com/gin-gonic/gin"
)

var startedAt = time.Now()

// InitLogger creates a structured JSON logger for production or text logger locally.
func InitLogger(env string) *slog.Logger {
	opts := &slog.HandlerOptions{Level: slog.LevelInfo}
	var handler slog.Handler
	if env == "production" {
		handler = slog.NewJSONHandler(os.Stdout, opts)
	} else {
		handler = slog.NewTextHandler(os.Stdout, opts)
	}
	logger := slog.New(handler)
	slog.SetDefault(logger)
	return logger
}

// InitSentry initializes Sentry with safe cost & PII defaults.
// Caller must `defer sentry.Flush(2 * time.Second)` in main().
func InitSentry(env, release string) error {
	dsn := os.Getenv("SENTRY_DSN")
	if dsn == "" || env != "production" {
		return nil
	}
	return sentry.Init(sentry.ClientOptions{
		Dsn:              dsn,
		Environment:      env,
		Release:          release,
		TracesSampleRate: 0.1,
		SendDefaultPII:   false,
	})
}

func newRequestID() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// Middleware attaches X-Request-Id, structured access logs, and Sentry scope tagging.
func Middleware(logger *slog.Logger) []gin.HandlerFunc {
	return []gin.HandlerFunc{
		sentrygin.New(sentrygin.Options{Repanic: true}),
		func(c *gin.Context) {
			reqID := c.GetHeader("X-Request-Id")
			if reqID == "" {
				reqID = newRequestID()
			}
			c.Set("request_id", reqID)
			c.Header("X-Request-Id", reqID)

			if hub := sentrygin.GetHubFromContext(c); hub != nil {
				hub.Scope().SetTag("request_id", reqID)
			}

			start := time.Now()
			c.Next()

			status := c.Writer.Status()
			level := slog.LevelInfo
			if status >= 500 {
				level = slog.LevelError
			} else if status >= 400 {
				level = slog.LevelWarn
			}

			logger.Log(c.Request.Context(), level, "http_request",
				"request_id", reqID,
				"method", c.Request.Method,
				"route", c.FullPath(), // Parameterized route, never raw IDs
				"status", status,
				"duration_ms", time.Since(start).Milliseconds(),
			)
		},
	}
}

// RegisterHealthRoutes mounts fast liveness (/healthz) and dependency readiness (/readyz).
func RegisterHealthRoutes(r *gin.Engine, version string, pingDeps func(context.Context) error) {
	r.GET("/healthz", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"status":   "ok",
			"version":  version,
			"uptime_s": int(time.Since(startedAt).Seconds()),
		})
	})

	r.GET("/readyz", func(c *gin.Context) {
		if pingDeps != nil {
			ctx, cancel := context.WithTimeout(c.Request.Context(), 1500*time.Millisecond)
			defer cancel()
			if err := pingDeps(ctx); err != nil {
				c.JSON(http.StatusServiceUnavailable, gin.H{"status": "degraded"})
				return
			}
		}
		c.JSON(http.StatusOK, gin.H{"status": "ready"})
	})
}

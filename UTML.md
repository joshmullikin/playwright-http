# UTML - UI Test Markup Language

UTML (UI Test Markup Language) is a JSON-based specification for describing browser automation tests. It provides a simple, declarative way to define test steps that can be executed by any UTML-compatible runner.

## Overview

UTML separates test definition from test execution:

- **Test authors** write JSON documents describing what to test
- **Executors** (like playwright-http) run the tests and return results
- **Generators** (like AI agents) can create UTML from natural language

This separation enables AI agents to generate and execute browser tests without writing code.

## Document Structure

A UTML document is a JSON object with the following structure:

```json
{
  "test_id": "optional-unique-id",
  "base_url": "https://example.com",
  "steps": [
    { "action": "navigate", "value": "/login" },
    { "action": "type", "target": "Email input", "value": "user@example.com" },
    { "action": "click", "target": "Submit button" }
  ],
  "options": {
    "browser": "chrome-headless",
    "timeout": 30000,
    "screenshot_on_failure": true
  }
}
```

### Root Properties

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `test_id` | string | No | Unique identifier for the test run. Auto-generated if not provided. |
| `base_url` | string | Yes | Base URL for the test. Relative paths in `navigate` actions are resolved against this. |
| `steps` | array | Yes | Array of test steps to execute in order. |
| `options` | object | No | Execution options (browser, timeout, etc.). |

### Options

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `browser` | string | Server default | Browser ID (e.g., `chrome-headless`, `firefox`). |
| `timeout` | integer | 30000 | Step timeout in milliseconds. |
| `screenshot_on_failure` | boolean | true | Capture screenshot when a step fails. |

## Test Step Schema

Each step in the `steps` array is an object:

```json
{
  "action": "click",
  "target": "Login button",
  "value": null,
  "description": "Click the login button to submit credentials"
}
```

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `action` | string | Yes | The action to perform. See [Actions Reference](#actions-reference). |
| `target` | string | No | Element to interact with. Supports natural language or CSS selectors. |
| `value` | string | No | Action-specific value (URL, text, time, etc.). |
| `description` | string | No | Human-readable description of the step's purpose. |

## Actions Reference

UTML supports 18 browser actions:

### Navigation

| Action | Description | Target | Value |
|--------|-------------|--------|-------|
| `navigate` | Navigate to URL | - | URL or path (e.g., `/login`, `https://example.com`) |
| `back` | Navigate back in history | - | - |

### Interaction

| Action | Description | Target | Value |
|--------|-------------|--------|-------|
| `click` | Click an element | Element description | - |
| `type` | Type text into input | Input element | Text to type |
| `fill_form` | Fill multiple form fields | - | JSON object: `{"field": "value", ...}` |
| `select` | Select dropdown option | Dropdown element | Option value or text |
| `hover` | Hover over element | Element description | - |
| `press_key` | Press keyboard key | - | Key name: `Enter`, `Tab`, `Escape`, etc. |
| `upload` | Upload file(s) | File input (optional) | File path or array of paths |
| `drag` | Drag element to target | Source element | Destination element |

### Waiting

| Action | Description | Target | Value |
|--------|-------------|--------|-------|
| `wait` | Wait for element or time | Element/text (optional) | Time in ms (optional) |
| `wait_for_page` | Wait for page load state | - | `load`, `domcontentloaded`, or `networkidle` |

### Assertions

| Action | Description | Target | Value |
|--------|-------------|--------|-------|
| `assert_text` | Verify text is visible | - | Expected text |
| `assert_element` | Verify element exists | Element description | - |
| `assert_style` | Verify CSS property | Element description | JSON: `{"property": "color", "expected": "red"}` |
| `assert_url` | Verify URL matches regex | - | Regex pattern |

### Utility

| Action | Description | Target | Value |
|--------|-------------|--------|-------|
| `screenshot` | Capture screenshot | Element (optional) | Filename (optional) |
| `evaluate` | Execute JavaScript | Element (optional) | JavaScript code |

## Element Targeting

The `target` field supports two modes:

### Natural Language

Describe elements as a human would:

```json
{"action": "click", "target": "Submit button"}
{"action": "type", "target": "Email input", "value": "test@example.com"}
{"action": "click", "target": "Accept cookies"}
```

The executor automatically:
1. Strips common suffixes (`button`, `link`, `input`, `field`, `text`, `icon`)
2. Tries multiple variations (e.g., "Submit button" → "Submit button" → "Submit")
3. Searches across roles (button, link, textbox) and text content

### CSS Selectors

Use standard CSS selectors for precise targeting:

```json
{"action": "click", "target": "#submit-btn"}
{"action": "type", "target": ".email-input", "value": "test@example.com"}
{"action": "click", "target": "input[type='submit']"}
```

CSS selectors are detected by the presence of `#`, `.`, `[`, or `>` characters.

## Examples

### Login Test

```json
{
  "base_url": "https://myapp.com",
  "steps": [
    {"action": "navigate", "value": "/login", "description": "Go to login page"},
    {"action": "type", "target": "Email input", "value": "user@example.com"},
    {"action": "type", "target": "Password input", "value": "secret123"},
    {"action": "click", "target": "Sign in button"},
    {"action": "wait_for_page", "value": "networkidle"},
    {"action": "assert_text", "value": "Welcome back", "description": "Verify successful login"}
  ]
}
```

### Form Submission with fill_form

```json
{
  "base_url": "https://myapp.com",
  "steps": [
    {"action": "navigate", "value": "/register"},
    {
      "action": "fill_form",
      "value": {
        "First name": "John",
        "Last name": "Doe",
        "Email": "john@example.com",
        "Password": "secure123"
      }
    },
    {"action": "click", "target": "Create account"},
    {"action": "assert_text", "value": "Registration successful"}
  ]
}
```

### E-commerce Checkout

```json
{
  "base_url": "https://shop.example.com",
  "steps": [
    {"action": "navigate", "value": "/products"},
    {"action": "click", "target": "Add to cart button"},
    {"action": "click", "target": "Cart icon"},
    {"action": "assert_text", "value": "1 item in cart"},
    {"action": "click", "target": "Checkout button"},
    {"action": "select", "target": "Shipping method", "value": "Express"},
    {"action": "fill_form", "value": {"Card number": "4111111111111111", "Expiry": "12/25", "CVV": "123"}},
    {"action": "click", "target": "Place order"},
    {"action": "wait", "target": "Order confirmed", "value": "10000"},
    {"action": "screenshot", "value": "order-confirmation.png"}
  ],
  "options": {
    "browser": "chrome-headless",
    "timeout": 60000
  }
}
```

### Using CSS Selectors

```json
{
  "base_url": "https://legacy-app.com",
  "steps": [
    {"action": "navigate", "value": "/"},
    {"action": "click", "target": "#nav-menu > .dropdown-toggle"},
    {"action": "type", "target": "input[name='search']", "value": "test query"},
    {"action": "click", "target": "button[type='submit']"},
    {"action": "assert_element", "target": ".search-results"}
  ]
}
```

## Implementations

### Executors
- **playwright-http** - Reference implementation (this repo)

### Generators
- **Checkmate** - AI-powered test case generator from natural language. *See our blog: [From "Test the Login Flow" to Running Tests](https://medium.com/@v31u) to learn how to build AI agents that generate UTML.*

## Version

UTML 1.0

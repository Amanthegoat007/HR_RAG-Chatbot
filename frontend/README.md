# Frontend Application

A React-based frontend for the Chatbot application, built with Vite and Mantine UI.

## Prerequisites

- **Node.js** (v18 or higher recommended)

## Setup

1.  **Install Dependencies:**
    ```bash
    npm install
    ```

2.  **Environment Configuration:**
    Create a `.env` file in the `frontend` directory. Check for any required variables (e.g., `VITE_API_URL` if not hardcoded).
    Example:
    ```env
    VITE_API_URL=http://localhost:5000/api
    ```

## Running the Application

### Development
Start the development server with hot module replacement (HMR):
```bash
npm run dev
```
Access the app at `http://localhost:5173` (or the port shown in terminal).

### Production Build
Type-check and build the application for production:
```bash
npm run build
```
To preview the production build locally:
```bash
npm run preview
```

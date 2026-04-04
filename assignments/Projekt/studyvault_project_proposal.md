# StudyVault — Project Proposal

## 1. Project overview

**StudyVault** is a cloud-native web application for secure upload, organization, search, preview, and sharing of academic and personal files such as PDFs, lecture notes, certificates, assignments, images, and project documents.

The main idea is to build a **digital vault for students** that combines:
- file storage
- metadata management
- search and filtering
- folder/tag organization
- favorites and recent activity
- optional sharing between users

This theme is a strong fit for the course because it naturally supports a **frontend + backend**, **microservice architecture**, **object storage**, **SQL + NoSQL databases**, **logging**, **CI/CD**, and **API gateway/proxy**.

---

## 2. Problem statement

Students often keep their files scattered across local folders, email attachments, messaging apps, and different cloud services. This makes it difficult to:
- find important documents quickly
- keep files organized by course or category
- track recent activity
- share documents in a structured way
- keep everything available through one clean interface

StudyVault solves this by providing a single web platform for file management with strong backend architecture.

---

## 3. Project goals

### Main goal
Build a cloud-native digital vault platform where users can upload, store, organize, search, and manage files through a modern web interface.

### Technical goals
- implement a microservice-based backend
- provide a web frontend for file management
- use at least one relational and one non-relational database
- use S3-compatible object storage for file contents
- expose services through an API gateway or reverse proxy
- collect centralized logs
- run services with Docker Compose
- set up a CI/CD pipeline

---

## 4. Target users

### Primary users
- students
- teaching assistants
- users who want to organize digital documents

### Example usage scenarios
- a student uploads lecture notes and tags them with `NUKS`, `backend`, `docker`
- a user creates folders such as `Semester 2`, `Certificates`, `Projects`
- a user searches for all PDF documents related to a specific course
- a user marks important files as favorites
- a user views recent uploads and downloads
- a user shares a file with another user

---

## 5. Core features

### Core implementation features
- user registration and login
- upload file
- list my files
- file metadata view
- rename and delete file
- create folders or collections
- add tags to files
- search by filename, tag, and type
- mark file as favorite
- recent activity log

### Additional features
- share files with other users
- PDF/image preview
- file version history
- admin dashboard
- download counter
- file size limits and upload validation
- public share link

---

## 6. Functional requirements

1. The system must allow a user to register and log in.
2. The system must allow authenticated users to upload files.
3. The system must store file contents in object storage.
4. The system must store metadata about files in a relational database.
5. The system must support creating folders and assigning tags.
6. The system must support searching files by name, tag, and type.
7. The system must allow users to rename, delete, favorite, and download files.
8. The system must record important user actions in an activity log.
9. The system should support sharing files with another user.
10. The system should provide a basic preview for supported file types.

---

## 7. Non-functional requirements

- responsive web interface
- secure authentication
- scalable service separation
- structured logging
- containerized deployment
- fault isolation between services
- basic caching for repeated queries
- clean REST API design

---

## 8. High-level architecture

```text
[ React Frontend ]
        |
        v
[ API Gateway / Nginx / Kong ]
        |
        +-------------------+-------------------+-------------------+-------------------+
        |                   |                   |                   |                   |
        v                   v                   v                   v                   v
[ Auth Service ]   [ File Service ]   [ Catalog Service ]   [ Search Service ]   [ Activity Service ]
        |                   |                   |                   |                   |
        |                   |                   |                   |                   |
        v                   v                   v                   v                   v
 [ PostgreSQL ]      [ MinIO / S3 ]      [ PostgreSQL ]         [ MongoDB ]         [ MongoDB ]
        ^                   |                   ^                   ^                   ^
        |                   |                   |                   |                   |
        +-------------------+-------------------+-------------------+-------------------+
                                optional Redis cache / event broker
```

### Architecture explanation
- **Frontend** handles login, dashboard, upload form, file listing, and search UI.
- **API Gateway** routes requests to backend services and can also handle rate limiting, proxying, and security rules.
- **Auth Service** manages users and authentication.
- **File Service** handles uploads, downloads, and interaction with MinIO/S3.
- **Catalog Service** manages folders, tags, file metadata, favorites, and sharing.
- **Search Service** supports filtering and searching through indexed metadata.
- **Activity Service** records user actions such as upload, delete, download, and share.

---

## 9. Microservices design

## 9.1 Auth Service
### Responsibilities
- user registration
- login
- password hashing
- JWT token issuing/validation
- user profile management
- role management (`user`, `admin`)

### Main endpoints
- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`
- `PUT /auth/me`

### Database
- PostgreSQL

---

## 9.2 File Service
### Responsibilities
- file upload
- file download
- delete file content
- file validation
- file storage in MinIO/S3
- metadata extraction (name, size, mime type)

### Main endpoints
- `POST /files/upload`
- `GET /files/{id}/download`
- `DELETE /files/{id}`
- `GET /files/{id}`

### Storage
- MinIO / S3 for binary content
- PostgreSQL for basic metadata reference or linked through Catalog Service

---

## 9.3 Catalog Service
### Responsibilities
- file metadata management
- folders
- tags
- favorites
- sharing permissions
- listing files by folder/category/user

### Main endpoints
- `GET /catalog/files`
- `PUT /catalog/files/{id}`
- `POST /catalog/folders`
- `GET /catalog/folders`
- `POST /catalog/files/{id}/tags`
- `POST /catalog/files/{id}/favorite`
- `POST /catalog/files/{id}/share`

### Database
- PostgreSQL

---

## 9.4 Search Service
### Responsibilities
- search by file name
- search by tags
- filter by type/size/date/folder
- indexing metadata
- full-text search over selected fields

### Main endpoints
- `GET /search?q=...`
- `GET /search/advanced?...`

### Database
- MongoDB

---

## 9.5 Activity Service
### Responsibilities
- store activity log events
- track uploads/downloads/deletes/logins
- provide recent activity feed
- audit trail for future admin view

### Example events
- `FILE_UPLOADED`
- `FILE_DELETED`
- `FILE_DOWNLOADED`
- `FILE_SHARED`
- `USER_LOGGED_IN`

### Main endpoints
- `GET /activity/recent`
- `GET /activity/file/{id}`

### Database
- MongoDB

---

## 10. Database design

## 10.1 Relational database (PostgreSQL)
Used for structured and strongly related data.

### Suggested tables

#### `users`
- id
- email
- password_hash
- full_name
- role
- created_at

#### `files`
- id
- owner_id
- folder_id
- object_key
- original_name
- mime_type
- size_bytes
- is_favorite
- created_at
- updated_at

#### `folders`
- id
- owner_id
- name
- parent_folder_id
- created_at

#### `tags`
- id
- name

#### `file_tags`
- file_id
- tag_id

#### `shares`
- id
- file_id
- shared_with_user_id
- permission_type
- created_at

### Why PostgreSQL?
Because users, files, folders, and permissions have clear relationships and benefit from relational integrity.

---

## 10.2 Non-relational database (MongoDB)
Used for flexible, event-based, and search-oriented data.

### Suggested collections

#### `activity_logs`
```json
{
  "userId": 12,
  "fileId": 88,
  "eventType": "FILE_UPLOADED",
  "timestamp": "2026-04-12T14:30:00Z",
  "metadata": {
    "fileName": "nuks-notes.pdf",
    "size": 2350012
  }
}
```

#### `search_index`
```json
{
  "fileId": 88,
  "ownerId": 12,
  "name": "nuks-notes.pdf",
  "tags": ["NUKS", "cloud", "docker"],
  "folder": "Semester 2",
  "mimeType": "application/pdf",
  "createdAt": "2026-04-12T14:30:00Z"
}
```

### Why MongoDB?
Because activity logs and search documents can vary in structure and grow quickly.

---

## 10.3 Object storage (MinIO / S3)
Used for actual binary files.

### Stored content
- uploaded PDFs
- images
- certificates
- notes
- optional preview thumbnails

### Example object key
- `user-12/semester-2/nuks-notes.pdf`

---

## 11. Cache and asynchronous communication

## Redis (optional but recommended)
Can be used for:
- caching search results
- caching file list responses
- caching session or token-related checks
- reducing repeated database load

## RabbitMQ / Kafka (optional bonus)
Can be used for event-driven communication:
- after file upload, publish `FILE_UPLOADED`
- activity service consumes event and stores log
- search service consumes event and updates search index

This is a good bonus if there is enough time, but not required for the core implementation.

---

## 12. Logging, monitoring, and observability

### Centralized logging
Possible stack:
- Grafana + Loki
- ELK (Elasticsearch, Logstash, Kibana)

### What to log
- authentication attempts
- upload and download actions
- service errors
- gateway requests
- failed validations
- internal service communication issues

### Monitoring
Possible stack:
- Prometheus + Grafana

### Useful metrics
- number of uploads
- number of downloads
- API response times
- service health status
- storage usage

---

## 13. CI/CD pipeline

### Example GitHub Actions pipeline
1. run lint
2. run tests
3. build frontend
4. build Docker images
5. optionally push images
6. deploy static frontend or prepare deployment artifacts

### Example jobs
- backend test job
- frontend build job
- Docker build job

---

## 14. Suggested tech stack

### Frontend
- React
- Vite
- Tailwind CSS (optional)
- Axios

### Backend
- Node.js + Express / NestJS
- or Python + FastAPI

### Databases and storage
- PostgreSQL
- MongoDB
- MinIO
- Redis (optional)

### Infrastructure
- Docker Compose
- Nginx or Kong
- GitHub Actions
- Cloudflare
- Grafana/Loki or ELK

### Recommended combination
A realistic and fast stack would be:
- React frontend
- Node.js / Express backend services
- PostgreSQL + MongoDB
- MinIO
- Redis
- Nginx gateway
- Grafana/Loki logging

---

## 15. Example API design

## Authentication
- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`

## File handling
- `POST /files/upload`
- `GET /files/{id}`
- `GET /files/{id}/download`
- `DELETE /files/{id}`

## Catalog
- `GET /catalog/files`
- `GET /catalog/folders`
- `POST /catalog/folders`
- `PUT /catalog/files/{id}`
- `POST /catalog/files/{id}/tags`
- `POST /catalog/files/{id}/favorite`

## Search
- `GET /search?q=pdf`
- `GET /search/advanced?tag=NUKS&type=pdf`

## Activity
- `GET /activity/recent`
- `GET /activity/file/{id}`

---

## 16. Frontend pages

### Public pages
- login page
- register page

### Authenticated pages
- dashboard
- my files
- upload page
- file details page
- folders page
- search results page
- shared with me page
- profile page

### Optional admin pages
- admin dashboard
- logs overview
- user overview

---

## 17. Project scope

### Must have
- authentication
- upload/download/delete
- file listing
- folders or tags
- search
- PostgreSQL + MongoDB integration
- MinIO integration
- API gateway
- Docker Compose
- centralized logging
- CI/CD pipeline

### Should have
- favorites
- recent activity
- file metadata page
- basic validation and error handling

### Nice to have
- sharing
- preview
- Redis cache
- async event processing
- admin panel

---

## 18. Stretch goals

- public share links
- version history for files
- thumbnail generation
- email notifications
- role-based access control
- file expiration links
- analytics dashboard

---

## 19. Security considerations

- password hashing with bcrypt/argon2
- JWT authentication
- file type validation
- file size limits
- authorization checks for all file access
- secure object key handling
- input validation on all endpoints
- audit logs for important actions

---

## 20. Deployment idea

### Docker Compose services
- frontend
- api-gateway
- auth-service
- file-service
- catalog-service
- search-service
- activity-service
- postgres
- mongodb
- minio
- redis (optional)
- grafana/loki or elk

### Domain and network
- Cloudflare in front
- reverse proxy routes traffic to frontend and API gateway

---

## 21. Example user flow

### Upload flow
1. user logs in
2. frontend sends upload request to API gateway
3. gateway forwards request to file service
4. file service stores binary object in MinIO
5. metadata is stored in PostgreSQL
6. upload event is sent to activity service
7. search service updates searchable metadata
8. frontend refreshes file list

### Search flow
1. user enters search query
2. frontend calls search endpoint
3. search service queries MongoDB index
4. results are returned and displayed

---

## 22. Milestone plan

## Milestone 1
- finalize idea
- define scope
- draw architecture sketch
- define user roles and main flows

## Milestone 2
- prepare API design
- define microservice boundaries
- define database models

## Milestone 3
- implement services
- connect frontend and backend
- run everything with Docker Compose

## Milestone 4
- add centralized logging
- finish CI/CD pipeline
- polish deployment and presentation

---

## 23. Risks and mitigation

### Risk: project becomes too large
**Mitigation:** keep the project focused on auth, upload, list, search, and activity.

### Risk: search service becomes complex
**Mitigation:** start with metadata search only, not full file content indexing.

### Risk: microservices take too long
**Mitigation:** keep services small and clearly scoped.

### Risk: sharing and preview consume time
**Mitigation:** move them to stretch goals.

---

## 24. Why this project is a good fit for the course

StudyVault is a strong course project because it naturally demonstrates:
- frontend and backend integration
- cloud-native architecture
- microservice segmentation
- Docker Compose deployment
- relational and non-relational data modeling
- object storage through S3 API
- centralized logging and observability
- CI/CD setup

It is realistic, technically rich, and still manageable within a semester.

---

## 25. Short presentation summary

**StudyVault** is a cloud-native digital vault web application for uploading, organizing, searching, and managing academic and personal files. The system is split into microservices for authentication, file management, catalog organization, search, and activity logging. File metadata is stored in PostgreSQL, flexible activity and search data in MongoDB, and actual files in MinIO using the S3 API. The application is deployed with Docker Compose and includes centralized logging, API gateway routing, and CI/CD support.

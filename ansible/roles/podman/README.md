# podman

Podman here accepts only images from an allowlist of registry repositories
(`/etc/containers/policy.json`, default `reject`). This role installs the policy with
`podman_allowed_repositories`, empty by default, so an image built from this role alone pulls
nothing. `quadlet_prepull` rewrites it at each image build with the repositories of the host's
`.image` files, before the first pull.

Consequences:

- A VM pulls only its own apps' images; `podman pull` of anything else is refused, as is
  `podman load` and every other non-registry transport.
- An app image must be declared in a Quadlet `.image` file with a fully qualified reference; short
  names are refused (`registries.conf.d/10-short-names.conf`).
- Already-stored images run without a policy check; the policy applies when an image is pulled.

import { render, screen } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { pageState } = vi.hoisted(() => ({
  pageState: {
    url: new URL('http://localhost:5173/'),
    params: {} as Record<string, string>,
    status: 500,
  },
}));

vi.mock('$app/state', () => ({ page: pageState }));

const ErrorPage = (await import('./+error.svelte')).default;

beforeEach(() => {
  pageState.status = 500;
});

describe('+error.svelte', () => {
  const cases = [
    {
      status: 404,
      heading: 'Page not found',
      body: "We couldn't find what you were looking for. It may have moved or never existed.",
    },
    {
      status: 403,
      heading: 'Not allowed',
      body: "You don't have access to this page.",
    },
    {
      status: 500,
      heading: 'Something went wrong',
      body: 'An unexpected error occurred. Try again in a moment.',
    },
  ] as const;

  for (const { status, heading, body } of cases) {
    it(`renders status ${status} with the right heading and body`, () => {
      pageState.status = status;
      render(ErrorPage);

      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(heading);
      expect(screen.getByText(body)).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Back to home' })).toHaveAttribute('href', '/');
    });
  }

  it('falls through to the generic copy for unrecognized statuses', () => {
    pageState.status = 418;
    render(ErrorPage);

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Something went wrong');
  });
});

import { render, screen } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import TextField from './TextField.svelte';

describe('TextField', () => {
  it('associates the label with the input and reflects the value', () => {
    render(TextField, { label: 'Page Name', value: 'Hello' });
    expect((screen.getByLabelText('Page Name') as HTMLInputElement).value).toBe('Hello');
  });

  it('renders read-only when readonly is set', () => {
    render(TextField, { label: 'URL', value: 'https://example.com', readonly: true });
    expect((screen.getByLabelText('URL') as HTMLInputElement).readOnly).toBe(true);
  });

  it('passes arbitrary input attributes through to the input', () => {
    render(TextField, {
      label: 'Name',
      value: '',
      autocomplete: 'off',
      'data-1p-ignore': true,
    });
    const input = screen.getByLabelText('Name');
    expect(input).toHaveAttribute('autocomplete', 'off');
    expect(input).toHaveAttribute('data-1p-ignore');
  });

  it('opts out of autofill when noAutofill is set', () => {
    render(TextField, { label: 'Name', value: '', noAutofill: true });
    const input = screen.getByLabelText('Name');
    expect(input).toHaveAttribute('autocomplete', 'off');
    expect(input).toHaveAttribute('data-1p-ignore');
    expect(input).toHaveAttribute('data-lpignore', 'true');
  });

  it('allows autofill by default', () => {
    render(TextField, { label: 'Name', value: '' });
    expect(screen.getByLabelText('Name')).not.toHaveAttribute('data-1p-ignore');
  });

  it('marks optional fields in the label', () => {
    render(TextField, { label: 'Author', value: '', optional: true });
    expect(screen.getByText('(optional)')).toBeInTheDocument();
  });
});

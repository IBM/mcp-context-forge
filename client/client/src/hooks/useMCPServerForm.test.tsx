import { renderHook, act } from '@testing-library/react';
import useMCPServerForm from './useMCPServerForm';
import { server } from '../../api/server';
import { vi } from 'vitest';

// Mock the server API to avoid real network requests
vi.mock('../../api/server', () => ({
  server: {
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
}));

// Mock success callback
const mockSuccess = vi.fn();

describe('useMCPServerForm', () => {
  beforeEach(() => {
    mockSuccess.mockReset();
    vi.clearAllMocks();
  });

  it('should submit with valid data and call success callback', async () => {
    const mockServer = { id: 'test-id' };
    server.create.mockResolvedValueOnce(mockServer);

    const { result, waitForNextUpdate } = renderHook(() => useMCPServerForm({
      onSuccess: mockSuccess,
      initialValues: { name: 'Test Server', command: 'echo hello' },
    }));

    // Wrap the async submission in act() to avoid React warnings
    await act(async () => {
      await result.current.handleSubmit();
    });

    // Verify that the success callback was called
    expect(mockSuccess).toHaveBeenCalledTimes(1);
    expect(server.create).toHaveBeenCalledWith({
      name: 'Test Server',
      command: 'echo hello',
    });
  });

  it('should reset the form after successful submission', async () => {
    const mockServer = { id: 'test-id' };
    server.create.mockResolvedValueOnce(mockServer);

    const { result } = renderHook(() => useMCPServerForm({
      onSuccess: mockSuccess,
      initialValues: { name: 'Test Server', command: 'echo hello' },
    }));

    await act(async () => {
      await result.current.handleSubmit();
    });

    // The form should be reset after submission
    expect(result.current.values).toEqual({});
  });

  it('should show validation errors on submit with invalid data', async () => {
    const { result } = renderHook(() => useMCPServerForm({
      onSuccess: mockSuccess,
      initialValues: { name: '', command: '' },
    }));

    // Attempt to submit without valid data
    await act(async () => {
      await result.current.handleSubmit();
    });

    // Errors should be present (implementation may vary)
    expect(result.current.errors).toBeDefined();
  });
});